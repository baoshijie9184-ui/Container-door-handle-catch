package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
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
    private static final String NAMESPACE = "HISTORICAL_LEDGER_ASSIGNMENT";
    private static final int MAX_ASSIGNMENTS = 500;
    private static final Pattern LEDGER_ID = Pattern.compile("[1-9][0-9]{0,18}");
    private static final String LEDGER_FROM = """
            FROM historical_detection_summary h
            LEFT JOIN runtime_state a ON a.namespace=:namespace AND a.owner_id=0
              AND a.scope_key=CONCAT(h.id, '') AND a.state_code='ASSIGNED'
            """;
    private static final String DISPLAY_JOINS = """
            LEFT JOIN model_management m ON m.model_id=h.model_id
            LEFT JOIN users u ON CONCAT(u.id, '')=a.current_ref
            LEFT JOIN employee e ON e.id=u.employee_id
            """;

    private final NamedParameterJdbcTemplate jdbc;
    private final BusinessUserDirectory users;
    private final BusinessAccountLookupApi accounts;
    private final ObjectMapper json;

    public HistoricalDetectionLedgerService(NamedParameterJdbcTemplate jdbc, BusinessUserDirectory users,
                                            BusinessAccountLookupApi accounts, ObjectMapper json) {
        this.jdbc = jdbc;
        this.users = users;
        this.accounts = accounts;
        this.json = json;
    }

    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Page list(String scope, int page, int size) {
        Identity actor = users.authenticated();
        String filter = switch (scope) {
            case "mine" -> "WHERE a.current_ref=:userId";
            case "all" -> {
                requireSupervisor(actor);
                yield "";
            }
            default -> throw new BusinessException(400, "未知历史台账查询范围");
        };
        var parameters = new MapSqlParameterSource("namespace", NAMESPACE)
                .addValue("userId", Long.toString(actor.userId()))
                .addValue("offset", (long) (page - 1) * size).addValue("size", size);
        long total = jdbc.queryForObject("SELECT COUNT(*) " + LEDGER_FROM + filter, parameters, Long.class);
        var records = jdbc.query("""
                SELECT h.id, h.model_id, m.model_name, h.detected_images_count, h.start_time, h.finished_at,
                       u.username AS assignee_username, e.name AS assignee_name, a.created_at AS assigned_at
                """ + LEDGER_FROM + DISPLAY_JOINS + filter + " ORDER BY h.start_time DESC, h.id DESC LIMIT :size OFFSET :offset",
                parameters, (row, index) -> {
                    LocalDateTime assignedAt = row.getObject("assigned_at", LocalDateTime.class);
                    return new Entry(row.getString("id"), row.getObject("model_id", Integer.class),
                            row.getString("model_name"), row.getObject("detected_images_count", Integer.class),
                            row.getObject("start_time", LocalDateTime.class), row.getObject("finished_at", LocalDateTime.class),
                            row.getString("assignee_username"), row.getString("assignee_name"),
                            assignedAt == null ? null : assignedAt.atOffset(ZoneOffset.UTC));
                });
        return new Page(records, total, page, size);
    }

    @Transactional(isolation = Isolation.READ_COMMITTED)
    public Assigned assign(Assignments request) {
        Identity actor = users.authenticated();
        requireSupervisor(actor);
        var requested = validate(request);
        var recipients = lockAccounts(actor, requested);
        var ids = requested.keySet().stream().map(String::valueOf).toList();

        // Lock existing ledger rows in the same order for overlapping requests, including previously unassigned rows.
        var ledgerRows = jdbc.queryForList("SELECT id FROM historical_detection_summary WHERE id IN (:rows) ORDER BY id FOR UPDATE",
                Map.of("rows", requested.keySet()), Long.class);
        if (ledgerRows.size() != requested.size()) {
            throw new BusinessException(404, "一条或多条历史台账记录不存在");
        }
        var parameters = new MapSqlParameterSource("namespace", NAMESPACE).addValue("ids", ids);
        Map<String, String> existing = jdbc.query("""
                SELECT scope_key, current_ref FROM runtime_state
                WHERE namespace=:namespace AND owner_id=0 AND scope_key IN (:ids) FOR UPDATE
                """, parameters, rows -> {
            var result = new HashMap<String, String>();
            while (rows.next()) result.put(rows.getString("scope_key"), rows.getString("current_ref"));
            return result;
        });

        LocalDateTime assignedAt = LocalDateTime.now(ZoneOffset.UTC).truncatedTo(ChronoUnit.MICROS);
        // The fixed runtime schema reserves actor_user_id for model-key revocations.
        String writer = json.createObjectNode().put("actorUserId", Long.toString(actor.userId())).toString();
        var inserts = new ArrayList<SqlParameterSource>();
        for (var assignment : requested.entrySet()) {
            String id = assignment.getKey().toString();
            String recipientId = recipients.get(assignment.getValue()).toString();
            if (existing.containsKey(id)) {
                if (!recipientId.equals(existing.get(id))) {
                    throw new BusinessException(409, "历史台账记录 " + id + " 已有其他责任人，请刷新后核对");
                }
            } else {
                inserts.add(new MapSqlParameterSource("namespace", NAMESPACE).addValue("id", id)
                        .addValue("recipientId", recipientId).addValue("writer", writer)
                        .addValue("assignedAt", assignedAt));
            }
        }
        if (!inserts.isEmpty()) {
            try {
                jdbc.batchUpdate("""
                        INSERT INTO runtime_state(namespace, owner_id, scope_key, state_code, current_ref,
                                                  payload_json, created_at, updated_at)
                        VALUES(:namespace, 0, :id, 'ASSIGNED', :recipientId, :writer, :assignedAt, :assignedAt)
                        """, inserts.toArray(SqlParameterSource[]::new));
            } catch (DuplicateKeyException conflict) {
                throw new BusinessException(409, "历史台账分派已变化，请刷新后核对");
            }
        }
        return new Assigned(inserts.size(), requested.size() - inserts.size(), requested.size());
    }

    private Map<String, Long> lockAccounts(Identity actor, Map<Long, String> assignments) {
        var recipientIds = new HashMap<String, Long>();
        var orderedAccounts = new TreeMap<Long, String>();
        orderedAccounts.put(actor.userId(), actor.username());
        for (String username : assignments.values().stream().distinct().toList()) {
            Long id = accounts.findExactUserId(username);
            if (id == null || id <= 0) throw invalidRecipient();
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
                    Identity current = users.lockCurrent(id, username);
                    if (!current.supervisor()) users.lockDetectionEmployee(id, username);
                } catch (SecurityException unavailable) {
                    throw invalidRecipient();
                }
            }
        }
        return recipientIds;
    }

    private static Map<Long, String> validate(Assignments request) {
        if (request == null || request.assignments() == null || request.assignments().isEmpty()
                || request.assignments().size() > MAX_ASSIGNMENTS) {
            throw new BusinessException(400, "请选择 1 至 500 条历史台账记录");
        }
        var assignments = new TreeMap<Long, String>();
        for (Assignment assignment : request.assignments()) {
            long id = parseId(assignment);
            String username = assignment.username();
            if (username == null || username.isBlank() || username.length() > 50) throw invalidRecipient();
            if (assignments.putIfAbsent(id, username) != null) {
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

    private static BusinessException invalidRecipient() {
        return new BusinessException(400, "责任人须为当前有效的主管或检测员工账号");
    }
}
