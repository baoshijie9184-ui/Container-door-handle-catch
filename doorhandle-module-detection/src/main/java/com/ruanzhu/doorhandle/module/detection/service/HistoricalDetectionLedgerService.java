package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Assigned;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Assignment;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Assignments;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Entry;
import com.ruanzhu.doorhandle.module.detection.dto.detection.HistoricalDetectionLedger.Page;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Pattern;

@Service
public class HistoricalDetectionLedgerService {
    private static final String NAMESPACE = "HISTORICAL_LEDGER_RESPONSIBILITY";
    private static final int MAX_ASSIGNMENTS = 500;
    private static final Pattern LEDGER_ID = Pattern.compile("[1-9][0-9]{0,18}");
    private static final String INSPECTOR_REF = "JSON_UNQUOTE(JSON_EXTRACT(a.payload_json,'$.inspectorEmployeeId'))";
    private static final String LEDGER_FROM = """
            FROM historical_detection_summary h
            LEFT JOIN runtime_state a ON a.namespace=:namespace AND a.owner_id=0
              AND a.scope_key=CONCAT(h.id, '') AND a.state_code='ASSIGNED'
            """;
    private static final String DISPLAY_JOINS = """
            LEFT JOIN model_management m ON m.model_id=h.model_id
            LEFT JOIN users supervisor ON CONCAT(supervisor.id, '')=a.current_ref
            LEFT JOIN employee supervisor_profile ON supervisor_profile.id=supervisor.employee_id
            LEFT JOIN employee inspector ON CONCAT(inspector.id, '')=%s
            LEFT JOIN users inspector_account ON inspector_account.employee_id=inspector.id
              AND inspector_account.role='INSPECTOR' AND inspector_account.enabled=1
              AND inspector.status='ACTIVE' AND inspector.employee_type='DETECTION'
            """.formatted(INSPECTOR_REF);
    private static final String OWN_AS_INSPECTOR = """
            WHERE EXISTS (SELECT 1 FROM users viewer JOIN employee profile ON profile.id=viewer.employee_id
                WHERE viewer.id=:userId AND viewer.role='INSPECTOR' AND viewer.enabled=1
                  AND profile.status='ACTIVE' AND profile.employee_type='DETECTION' AND CONCAT(profile.id, '')=%s)
            """.formatted(INSPECTOR_REF);

    private record RequestedPair(String supervisorUsername, String inspectorNumber) {}
    private record StoredPair(String supervisorUserId, String inspectorEmployeeId) {}

    private final NamedParameterJdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final BusinessAccountLookupApi accounts;
    private final EmployeeDirectoryApi employees;
    private final ObjectMapper json;

    public HistoricalDetectionLedgerService(NamedParameterJdbcTemplate jdbc, BusinessUserDirectory users,
                                            BusinessAccountLookupApi accounts, EmployeeDirectoryApi employees,
                                            ObjectMapper json) {
        this.jdbc = jdbc;
        this.users = users;
        this.accounts = accounts;
        this.employees = employees;
        this.json = json;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Page list(String scope, int page, int size) {
        Identity actor = users.authenticated();
        String filter = switch (scope) {
            case "mine" -> actor.supervisor() ? "WHERE a.current_ref=:userRef" : OWN_AS_INSPECTOR;
            case "all" -> {
                requireSupervisor(actor);
                yield "";
            }
            default -> throw new BusinessException(400, "未知历史台账查询范围");
        };
        var parameters = new MapSqlParameterSource("namespace", NAMESPACE)
                .addValue("userId", actor.userId()).addValue("userRef", Long.toString(actor.userId()))
                .addValue("offset", (long) (page - 1) * size).addValue("size", size);
        long total = jdbc.queryForObject("SELECT COUNT(*) " + LEDGER_FROM + filter, parameters, Long.class);
        var records = jdbc.query("""
                SELECT h.id, h.model_id, m.model_name, h.detected_images_count, h.start_time, h.finished_at,
                       supervisor.username AS supervisor_username, supervisor_profile.name AS supervisor_name,
                       inspector.employee_number AS inspector_number, inspector.name AS inspector_name,
                       inspector_account.username AS inspector_username, a.created_at AS assigned_at
                """ + LEDGER_FROM + DISPLAY_JOINS + filter + " ORDER BY h.start_time DESC, h.id DESC LIMIT :size OFFSET :offset",
                parameters, (row, index) -> {
                    LocalDateTime assignedAt = row.getObject("assigned_at", LocalDateTime.class);
                    return new Entry(row.getString("id"), row.getObject("model_id", Integer.class),
                            row.getString("model_name"), row.getObject("detected_images_count", Integer.class),
                            row.getObject("start_time", LocalDateTime.class), row.getObject("finished_at", LocalDateTime.class),
                            row.getString("supervisor_username"), row.getString("supervisor_name"),
                            row.getString("inspector_number"), row.getString("inspector_name"),
                            row.getString("inspector_username"),
                            assignedAt == null ? null : assignedAt.atOffset(ZoneOffset.UTC));
                });
        return new Page(records, total, page, size);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Assigned assign(Assignments request) {
        Identity actor = users.authenticated();
        requireSupervisor(actor);
        var requested = validate(request);
        var supervisors = lockSupervisors(actor, requested);
        var inspectors = lockInspectors(requested);
        var ids = requested.keySet().stream().map(String::valueOf).toList();

        // Lock existing ledger rows in the same order for overlapping requests, including previously unassigned rows.
        var ledgerRows = jdbc.queryForList("SELECT id FROM historical_detection_summary WHERE id IN (:rows) ORDER BY id FOR UPDATE",
                Map.of("rows", requested.keySet()), Long.class);
        if (ledgerRows.size() != requested.size()) {
            throw new BusinessException(404, "一条或多条历史台账记录不存在");
        }
        var parameters = new MapSqlParameterSource("namespace", NAMESPACE).addValue("ids", ids);
        Map<String, StoredPair> existing = jdbc.query("""
                SELECT a.scope_key, a.current_ref, %s AS inspector_ref FROM runtime_state a
                WHERE a.namespace=:namespace AND a.owner_id=0 AND a.scope_key IN (:ids) FOR UPDATE
                """.formatted(INSPECTOR_REF), parameters, rows -> {
            var result = new HashMap<String, StoredPair>();
            while (rows.next()) {
                result.put(rows.getString("scope_key"), new StoredPair(rows.getString("current_ref"), rows.getString("inspector_ref")));
            }
            return result;
        });

        LocalDateTime assignedAt = LocalDateTime.now(ZoneOffset.UTC).truncatedTo(ChronoUnit.MICROS);
        // The fixed runtime schema reserves actor_user_id for model-key revocations.
        String writer = Long.toString(actor.userId());
        var inserts = new ArrayList<SqlParameterSource>();
        for (var assignment : requested.entrySet()) {
            String id = assignment.getKey().toString();
            var pair = assignment.getValue();
            var resolved = new StoredPair(supervisors.get(pair.supervisorUsername()).toString(),
                    inspectors.get(pair.inspectorNumber()).toString());
            var prior = existing.get(id);
            if (prior != null) {
                if (!resolved.equals(prior)) {
                    throw new BusinessException(409, "历史台账记录 " + id + " 已有不同的责任分工，请刷新后核对");
                }
            } else {
                String evidence = json.createObjectNode().put("inspectorEmployeeId", resolved.inspectorEmployeeId())
                        .put("actorUserId", writer).toString();
                inserts.add(new MapSqlParameterSource("namespace", NAMESPACE).addValue("id", id)
                        .addValue("supervisorId", resolved.supervisorUserId()).addValue("evidence", evidence)
                        .addValue("assignedAt", assignedAt));
            }
        }
        if (!inserts.isEmpty()) {
            try {
                jdbc.batchUpdate("""
                        INSERT INTO runtime_state(namespace, owner_id, scope_key, state_code, current_ref,
                                                  payload_json, created_at, updated_at)
                        VALUES(:namespace, 0, :id, 'ASSIGNED', :supervisorId, :evidence, :assignedAt, :assignedAt)
                        """, inserts.toArray(SqlParameterSource[]::new));
            } catch (DuplicateKeyException conflict) {
                throw new BusinessException(409, "历史台账分派已变化，请刷新后核对");
            }
        }
        return new Assigned(inserts.size(), requested.size() - inserts.size(), requested.size());
    }

    private Map<String, Long> lockSupervisors(Identity actor, Map<Long, RequestedPair> assignments) {
        var recipientIds = new HashMap<String, Long>();
        var orderedAccounts = new TreeMap<Long, String>();
        orderedAccounts.put(actor.userId(), actor.username());
        for (String username : assignments.values().stream().map(RequestedPair::supervisorUsername).distinct().toList()) {
            Long id = accounts.findExactUserId(username);
            if (id == null || id <= 0) throw invalidSupervisor();
            String priorName = orderedAccounts.putIfAbsent(id, username);
            if (priorName != null && !priorName.equals(username)) {
                throw new BusinessException(409, "责任人账号已变化，请刷新后核对");
            }
            recipientIds.put(username, id);
        }
        for (var account : orderedAccounts.entrySet()) {
            long id = account.getKey();
            String username = account.getValue();
            if (id == actor.userId()) {
                requireSupervisor(users.lockCurrent(id, actor.username()));
            } else {
                try {
                    if (!users.lockCurrent(id, username).supervisor()) throw invalidSupervisor();
                } catch (SecurityException unavailable) {
                    throw invalidSupervisor();
                }
            }
        }
        return recipientIds;
    }

    private Map<String, Long> lockInspectors(Map<Long, RequestedPair> assignments) {
        var numbers = assignments.values().stream().map(RequestedPair::inspectorNumber).distinct().toList();
        var ids = jdbc.query("SELECT id, employee_number FROM employee WHERE employee_number IN (:numbers)",
                Map.of("numbers", numbers), rows -> {
                    var found = new HashMap<String, Long>();
                    while (rows.next()) found.put(rows.getString("employee_number"), rows.getLong("id"));
                    return found;
                });
        var ordered = new TreeMap<Long, String>();
        for (String number : numbers) {
            Long id = ids.get(number);
            if (id == null) throw invalidInspector();
            ordered.put(id, number);
        }
        for (var candidate : ordered.entrySet()) {
            var employee = employees.lock(candidate.getKey());
            if (employee == null || !candidate.getValue().equals(employee.employeeNumber())
                    || !"ACTIVE".equals(employee.status()) || !"DETECTION".equals(employee.employeeType())) {
                throw invalidInspector();
            }
        }
        return ids;
    }

    private static Map<Long, RequestedPair> validate(Assignments request) {
        if (request == null || request.assignments() == null || request.assignments().isEmpty()
                || request.assignments().size() > MAX_ASSIGNMENTS) {
            throw new BusinessException(400, "请选择 1 至 500 条历史台账记录");
        }
        var assignments = new TreeMap<Long, RequestedPair>();
        for (Assignment assignment : request.assignments()) {
            long id = parseId(assignment);
            String supervisor = assignment.supervisorUsername();
            String inspector = assignment.inspectorEmployeeNumber();
            if (supervisor == null || supervisor.isBlank() || supervisor.length() > 50) throw invalidSupervisor();
            if (inspector == null || inspector.isBlank() || inspector.length() > 50) throw invalidInspector();
            if (assignments.putIfAbsent(id, new RequestedPair(supervisor, inspector)) != null) {
                throw new BusinessException(400, "同一历史台账记录不能在本批次重复提交");
            }
        }
        return assignments;
    }

    private static long parseId(Assignment assignment) {
        if (assignment != null && assignment.id() != null && assignment.id().isTextual()) {
            String id = assignment.id().textValue();
            if (LEDGER_ID.matcher(id).matches()) {
                try {
                    return Long.parseLong(id);
                } catch (NumberFormatException tooLarge) {
                    throw new BusinessException(400, "历史台账记录编号超出范围");
                }
            }
        }
        throw new BusinessException(400, "历史台账记录编号须为正整数十进制字符串");
    }

    private static void requireSupervisor(Identity actor) {
        if (!actor.supervisor()) throw new BusinessException(403, "仅主管可查看全部历史台账或分派责任人");
    }

    private static BusinessException invalidSupervisor() {
        return new BusinessException(400, "请选择当前有效的主管账号");
    }

    private static BusinessException invalidInspector() {
        return new BusinessException(400, "请选择当前在岗检测人员的工号");
    }
}
