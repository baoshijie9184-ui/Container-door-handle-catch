package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeAccountNumbers;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeNumberDirectory;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeNumberDirectory.EmployeeLabel;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl;
import com.ruanzhu.doorhandle.module.infra.service.OssPreviewStorage;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import com.ruanzhu.doorhandle.module.detection.service.detection.DetectionRetryPolicy;
import com.ruanzhu.doorhandle.module.detection.service.detection.UploadFolders;
import com.ruanzhu.doorhandle.module.detection.service.detection.DetectionUploadMetadataStore;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.nio.charset.StandardCharsets;
import java.util.*;

@Service
@RequiredArgsConstructor
public class FolderTaskBoard {
    public record Recipient(String username, long userId, String revision) {}
    public record Create(UUID requestId, String prefix, Recipient recipient) {}
    public record Assign(int version, Recipient recipient) {}
    public record ApplicationDispatch(Integer expectedVersion, String uploadTaskId) {}
    public record Folder(String prefix, List<String> folders, int imagesOnPage, String next) {}

    private final NamedParameterJdbcTemplate db;
    private final OssPreviewStorage storage;
    private final DetectionTaskServiceImpl detection;
    private final DetectionTaskAccessPolicy access;
    private final BusinessUserDirectory users;
    private final EmployeeAccountNumbers staff;
    private final EmployeeNumberDirectory personnel;
    private final AgentUserDirectory employees;
    private final com.ruanzhu.doorhandle.module.infra.service.OssStorageService uploadStorage;
    private final DetectionUploadMetadataStore uploadMetadata;
    private final DetectionWorkUnitAudit workUnitAudit;
    private final ObjectMapper json;
    @Value("${detection.max-images-per-batch:200}") private int maxImages;

    private static final String SOURCE = " FROM detection_task t LEFT JOIN detection_work_unit w ON w.work_unit_id=t.task_id COLLATE utf8mb4_0900_ai_ci AND w.strategy='OSS_FOLDER' ";
    private static final String UPLOAD_TYPES = "t.task_type IN ('BATCH','BATCH_DIRECT')";
    private static final String FORMAL_VERIFICATION_TASK = BusinessDetectionTasks.dispatchedFolderForUpload("t.");
    private static final String FORMAL_VERIFICATION_ONLY = BusinessDetectionTasks.verificationTaskFilter("t.");
    private static final Set<String> BOARD_PHASES = Set.of("READY","DETECTING","VERIFYING","DONE","FAILED","MODEL_DONE");
    private static final Map<String,Set<String>> SUPERVISOR_LISTS = Map.of(
            "detection", Set.of("UPLOADING","READY","DETECTING","FAILED","CANCELLED","MODEL_DONE"),
            "verification", Set.of("WAITING_CHECK","VERIFYING","CHECKED","FOLLOW_UP"));
    // Older completed runs can have no verification record. They remain in the detection list.
    private static final String LIST_PHASE = """
        CASE WHEN t.status='FAILED' AND t.flow_status='RECHECK_REQUIRED' THEN 'FOLLOW_UP'
             WHEN t.status IN ('COMPLETED','PARTIAL_FAILED') THEN CASE
                  WHEN t.flow_status IN ('RECHECK_REQUIRED','REWORK_REQUIRED','HOLD')
                       OR (t.flow_status='CONFIRMED' AND t.review_conclusion='NEEDS_RECHECK') THEN 'FOLLOW_UP'
                  WHEN t.review_status='PENDING' AND t.flow_status='REVIEWING' THEN 'VERIFYING'
                  WHEN t.review_status='PENDING' AND t.flow_status='PENDING_REVIEW' THEN 'WAITING_CHECK'
                  WHEN t.review_status='REVIEWED' OR t.reviewed_at IS NOT NULL THEN 'CHECKED'
                  WHEN t.flow_status='REVIEWING' THEN 'VERIFYING'
                  WHEN t.review_status='PENDING' OR t.flow_status='PENDING_REVIEW' THEN 'WAITING_CHECK'
                  ELSE 'MODEL_DONE' END
             WHEN t.status IN ('FAILED','CANCELLED','UPLOADING') THEN t.status
             WHEN t.status IN ('READY','UPLOADED','PENDING') THEN 'READY'
             ELSE 'DETECTING' END
        """;
    // Aggregate filters and the two supervisor lists use the same stage evidence.
    private static final String PHASE = "CASE (" + LIST_PHASE + ") " + """
        WHEN 'WAITING_CHECK' THEN 'VERIFYING' WHEN 'FOLLOW_UP' THEN 'VERIFYING'
        WHEN 'CHECKED' THEN 'DONE' WHEN 'UPLOADING' THEN 'READY' WHEN 'CANCELLED' THEN 'FAILED'
        WHEN 'MODEL_DONE' THEN 'MODEL_DONE' WHEN 'VERIFYING' THEN 'VERIFYING'
        WHEN 'READY' THEN 'READY' WHEN 'FAILED' THEN 'FAILED' ELSE 'DETECTING' END
        """;
    private static final String COLUMNS = """
        t.task_id AS taskId,t.task_type AS taskType,t.image_folder_name AS folder,t.source_oss_prefix AS prefix,
        CAST(t.version AS CHAR) AS mutationVersion,
        t.model_version AS model,t.status AS modelStatus,t.flow_status AS flow,t.review_status AS reviewStatus,
        CASE WHEN t.flow_status='RECHECK_REQUIRED' THEN t.original_image_keys_json END AS recheckOriginalKeys,
        t.total_images AS totalImages,t.processed_images AS processedImages,t.failed_images AS failedImages,
        t.assignee AS qualityAssignee,t.reviewer AS qualityOperator,t.reviewed_at AS reviewedAt,
        w.assigned_user_name AS detector,w.version AS assignmentVersion,
        w.assignee_user_id AS detectorNameId,
        CASE WHEN t.reviewer_user_id IS NOT NULL OR NULLIF(t.reviewer,'') IS NOT NULL
             THEN t.reviewer_user_id ELSE t.assignee_user_id END AS verifierNameId,
        CASE WHEN w.submitted_at IS NOT NULL AND t.status IN ('COMPLETED','PARTIAL_FAILED') THEN w.assigned_user_name END AS detectionOperator,
        CASE WHEN w.assignee_user_id=CAST(:actor AS CHAR) THEN 1 ELSE 0 END AS mine,
        t.created_at AS createdAt, t.created_by AS creator,
        DATE_FORMAT(t.created_at,'%Y-%m-%d %H:%i:%s') AS registeredAt
        """;

    public PageRows list(String phase, String keyword, String directory, boolean inbox, boolean uploadsOnly, String assignedTaskId, String taskList, String inboxKind, int page, int size) {
        var actor = users.authenticated();
        var scope = access.currentSqlScope("t.");
        var args = new MapSqlParameterSource(scope.parameters()).addValue("actor",actor.userId()).addValue("username",actor.username());
        String qualityAssignee = access.qualityAssigneeSql("t.",":actor",":username");
        String where = " WHERE ("+scope.predicate()+" OR w.assignee_user_id=CAST(:actor AS CHAR))";
        String columns = COLUMNS+", CASE WHEN "+qualityAssignee+" THEN 1 ELSE 0 END AS qualityMine, "
                +PHASE+" AS phase, "+LIST_PHASE+" AS listPhase";
        String filterPhase = PHASE;
        Set<String> allowedPhases = BOARD_PHASES;
        if (taskList != null || inbox) where += " AND " + BusinessDetectionTasks.filter("t.");
        if (taskList != null) {
            if (!actor.supervisor()) throw new BusinessException(403,"仅主管可查看企业任务列表");
            allowedPhases = SUPERVISOR_LISTS.get(taskList);
            if (allowedPhases == null) throw bad("未知任务列表");
            filterPhase = LIST_PHASE;
            where += " AND ("+LIST_PHASE+") IN (:listPhases)";
            if ("verification".equals(taskList)) where += " AND "+FORMAL_VERIFICATION_ONLY;
            args.addValue("listPhases", allowedPhases);
        }
        if (assignedTaskId != null) {
            where += " AND t.task_id=:assignedTaskId AND w.assignee_user_id=CAST(:actor AS CHAR)";
            args.addValue("assignedTaskId",assignedTaskId);
        }
        if (uploadsOnly) where += " AND "+UPLOAD_TYPES;
        if (directory != null && !directory.isBlank()) {
            validatePrefix(directory);
            where += " AND BINARY t.source_oss_prefix=BINARY :directory";
            args.addValue("directory",directory);
        }
        if (inboxKind != null && (!inbox || !Set.of("detection","verification").contains(inboxKind)))
            throw bad("未知待办类型");
        if (inbox) {
            String detect = "(w.assignee_user_id=CAST(:actor AS CHAR) AND t.status IN ('READY','FAILED') AND COALESCE(t.flow_status,'')<>'RECHECK_REQUIRED')";
            String verify = "("+qualityAssignee+" AND ("
                    +"(t.status IN ('COMPLETED','PARTIAL_FAILED') AND t.flow_status IN ('PENDING_REVIEW','REVIEWING') AND t.review_status='PENDING')"
                    +" OR ("+LIST_PHASE+")='FOLLOW_UP') AND "+FORMAL_VERIFICATION_ONLY+")";
            String pending = inboxKind == null ? detect+" OR "+verify : "detection".equals(inboxKind) ? detect : verify;
            where += " AND ("+pending+")";
        }
        if (phase != null && !phase.isBlank()) {
            if (!allowedPhases.contains(phase)) throw bad("未知任务阶段");
            where += " AND ("+filterPhase+")=:phase"; args.addValue("phase",phase);
        }
        if (keyword != null && !keyword.isBlank()) {
            if(keyword.length()>255) throw bad("搜索内容过长");
            where+="""
                 AND (LOCATE(:q,t.task_id)>0 OR LOCATE(:q,t.image_folder_name)>0 OR LOCATE(:q,t.source_oss_prefix)>0
                   OR LOCATE(:q,t.created_by)>0 OR LOCATE(:q,w.assigned_user_name)>0 OR LOCATE(:q,t.assignee)>0
                   OR LOCATE(:q,t.reviewer)>0 OR EXISTS (SELECT 1 FROM detection_work_unit a
                       WHERE a.work_unit_id=:q AND a.batch_id=w.work_unit_id AND a.strategy<>'OSS_FOLDER'))
                """;
            args.addValue("q",keyword.strip());
        }
        var result = readPage(columns,SOURCE,where,args,page,size);
        populateStageNames(result.items());
        for (var row : result.items()) {
            var originalKeys = (String)row.remove("recheckOriginalKeys");
            if ("RECHECK_REQUIRED".equals(row.get("flow"))) {
                row.put("recheckBlockedReason", DetectionRetryPolicy.originalImageEvidenceReason(originalKeys,json));
            }
        }
        return result;
    }

    public PageRows uploads(String scope, String uploader, String keyword, String phase, boolean awaitingDispatch, int page, int size) {
        var actor = users.authenticated();
        if (scope == null) scope = actor.supervisor() ? "team" : "mine";
        if (!Set.of("mine","team").contains(scope)) throw bad("未知上传记录范围");
        var taskScope = access.currentSqlScope("t.");
        String readable = "("+taskScope.predicate()+")";
        var args = new MapSqlParameterSource(taskScope.parameters());
        String where = " WHERE "+UPLOAD_TYPES;
        if (awaitingDispatch) {
            if (!actor.supervisor()) throw new BusinessException(403,"仅主管可查看待派文件夹");
            where += " AND "+BusinessDetectionTasks.filter("t.")+"""
                 AND t.status NOT IN ('UPLOADING','CANCELLED') AND t.total_images>0
                 AND t.source_oss_prefix LIKE 'detection/%/'
                 AND NOT EXISTS (SELECT 1 FROM detection_task f WHERE f.task_type='OSS_FOLDER'
                     AND f.status <> 'CANCELLED' AND BINARY f.source_oss_prefix=BINARY t.source_oss_prefix)
                """;
        }
        if (scope.equals("mine")) {
            where += " AND (t.created_user_id=:ownerId OR (t.created_user_id IS NULL AND BINARY t.created_by=BINARY :ownerName))";
            args.addValue("ownerId",actor.userId()).addValue("ownerName",actor.username());
        }
        if (uploader != null && !uploader.isBlank()) {
            if (uploader.length()>64) throw bad("上传账号过长");
            String name = uploader.strip();
            var matches=personnel.findByNumbers(List.of(name));
            if (matches.isEmpty()) return new PageRows(0,List.of());
            String number=matches.get(0).employeeNumber();
            var owner=staff.resolve(List.of(),List.of(number)).stream().filter(a->number.equals(a.employee().employeeNumber())).findFirst();
            where += " AND (t.created_user_id=:uploaderId OR (t.created_user_id IS NULL AND BINARY t.created_by=BINARY :number))";
            args.addValue("number",number).addValue("uploaderId",owner.map(EmployeeAccountNumbers.BoundAccount::userId).orElse(null));
        }
        if (keyword != null && !keyword.isBlank()) {
            if (keyword.length()>255) throw bad("搜索内容过长");
            where += " AND (LOCATE(:q,t.task_id)>0 OR LOCATE(:q,t.image_folder_name)>0 OR LOCATE(:q,t.created_by)>0 OR ("+readable+" AND LOCATE(:q,t.source_oss_prefix)>0))";
            args.addValue("q",keyword.strip());
        }
        if (phase != null && !phase.isBlank()) {
            if (!BOARD_PHASES.contains(phase)) throw bad("未知任务阶段");
            where += " AND "+readable+" AND ("+PHASE+")=:phase";
            args.addValue("phase",phase);
        }
        // Shared rows expose upload registration only. Folder paths and processing data follow task read access.
        String permitted = "CASE WHEN "+readable+" THEN ";
        String columns = """
            t.task_id AS taskId,t.task_type AS taskType,t.image_folder_name AS folder,t.created_by AS recordedName,t.created_user_id AS recordedId,t.total_images AS totalImages,
            DATE_FORMAT(t.created_at,'%Y-%m-%d %H:%i:%s') AS registeredAt,
            (t.status='UPLOADING') AS uploadPending,
            """+permitted+"1 ELSE 0 END AS canReadTask, "
            +permitted+"t.source_oss_prefix END AS prefix, "+permitted+PHASE+" END AS phase, "
            +permitted+LIST_PHASE+" END AS listPhase, "+permitted+"t.status END AS modelStatus, "
            +permitted+"t.review_status END AS reviewStatus, "
            +permitted+"t.processed_images END AS processedImages, "+permitted+"t.failed_images END AS failedImages";
        if (actor.supervisor()) {
            columns += ", "+permitted+"("+FORMAL_VERIFICATION_TASK+" ORDER BY f.id DESC LIMIT 1) END AS formalVerificationTaskId";
        }
        var result=readPage(columns," FROM detection_task t",where,args,page,size);
        populateUploaderLabels(result.items());
        for (var row : result.items()) {
            if (!permittedRow(row)) row.put("folder", shortName((String) row.get("folder")));
        }
        if (!actor.supervisor() && !result.items().isEmpty()) addMyDetectionTasks(result.items(), actor.userId());
        return result;
    }

    private void populateUploaderLabels(List<Map<String,Object>> rows) {
        var ids=new HashSet<Long>();
        var names=new HashSet<String>();
        for (var row:rows) {
            collectPerson(row.get("recordedId"), row.get("recordedName"), ids, names);
        }
        var labels = resolveLabels(ids, names);
        for (var row:rows) {
            var uploaderLabel = labels.find(row.remove("recordedId"), row.remove("recordedName"));
            row.put("creator",uploaderLabel == null ? null : uploaderLabel.employeeNumber());
            row.put("creatorName",name(uploaderLabel));
        }
    }

    private void populateStageNames(List<Map<String,Object>> rows) {
        var ids = new HashSet<Long>();
        var accounts = new HashSet<String>();
        for (var row : rows) {
            collectPerson(row.get("detectorNameId"), row.get("detector"), ids, accounts);
            collectPerson(row.get("verifierNameId"), verifierAccount(row), ids, accounts);
        }
        var labels = resolveLabels(ids, accounts);
        for (var row : rows) {
            var detector = labels.find(row.remove("detectorNameId"), row.get("detector"));
            var verifier = labels.find(row.remove("verifierNameId"), verifierAccount(row));
            row.put("detectorName", name(detector));
            row.put("detectorEmployeeNumber", detector == null ? null : detector.employeeNumber());
            row.put("verifierName", name(verifier));
            row.put("verifierEmployeeNumber", verifier == null ? null : verifier.employeeNumber());
        }
    }

    private static Object verifierAccount(Map<String,Object> row) {
        return row.get("qualityOperator") instanceof String reviewer && !reviewer.isBlank() ? reviewer : row.get("qualityAssignee");
    }

    private static void collectPerson(Object id, Object account, Set<Long> ids, Set<String> accounts) {
        Long identifier = accountId(id);
        if (identifier != null) ids.add(identifier);
        else if (account instanceof String value && !value.isBlank()) accounts.add(value);
    }

    private static Long accountId(Object id) {
        if (id instanceof Number number) return number.longValue();
        if (id instanceof String value) {
            try { return Long.valueOf(value); } catch (NumberFormatException legacy) { return null; }
        }
        return null;
    }

    private static String name(EmployeeLabel label) {
        return label == null ? null : label.name();
    }

    private record EmployeeLabels(Map<Long,EmployeeLabel> byId, Map<String,EmployeeLabel> byAccount) {
        EmployeeLabel find(Object id, Object account) {
            Long identifier = accountId(id);
            return identifier != null ? byId.get(identifier) : byAccount.get(account);
        }
    }

    private EmployeeLabels resolveLabels(Set<Long> ids, Set<String> names) {
        var byId=new HashMap<Long,EmployeeLabel>();
        var byName=new HashMap<String,EmployeeLabel>();
        for (var person:staff.resolve(ids,names)) {
            byId.put(person.userId(),person.employee());
            byName.put(person.username(),person.employee());
        }
        names.removeAll(byName.keySet());
        for (var employee:personnel.findByNumbers(names)) byName.put(employee.employeeNumber(),employee);
        return new EmployeeLabels(byId, byName);
    }

    private static boolean permittedRow(Map<String,Object> row) {
        Object value = row.get("canReadTask");
        return Boolean.TRUE.equals(value) || value instanceof Number n && n.intValue() != 0;
    }

    private static String shortName(String name) {
        if (name == null) return null;
        String[] parts = name.replace((char) 92, '/').split("/");
        int i = parts.length - 1;
        if (i > 0 && parts[i].matches("(?i)originals?")) i--;
        return i < 0 ? null : parts[i].strip();
    }

    @Transactional(readOnly = true)
    public Map<String,Object> folderMetadata(String taskId) {
        var actor = users.authenticated();
        var scope = access.currentSqlScope("t.");
        var args = new MapSqlParameterSource(scope.parameters()).addValue("actor",actor.userId()).addValue("id",taskId);
        String readable = "(" + scope.predicate() + " OR w.assignee_user_id=CAST(:actor AS CHAR))";
        // Keep shared upload registration public within the board. Only task readers get capture and storage details.
        // A dispatched folder can inherit its upload registration only when the exact OSS prefix identifies one upload.
        String sql = """
                SELECT t.task_id AS taskId, t.image_folder_name AS folder, t.total_images AS totalImages,
                       CASE WHEN t.task_type='OSS_FOLDER' THEN u.created_user_id ELSE t.created_user_id END AS recordedId,
                       CASE WHEN t.task_type='OSS_FOLDER' THEN u.created_by ELSE t.created_by END AS recordedName,
                       DATE_FORMAT(COALESCE(u.created_at,t.created_at),'%%Y-%%m-%%d %%H:%%i:%%s') AS registeredAt,
                       CASE WHEN %1$s THEN 1 ELSE 0 END AS canReadTask,
                       CASE WHEN %1$s THEN t.source_oss_prefix END AS prefix,
                       CASE WHEN %1$s THEN t.task_type END AS taskType,
                       CASE WHEN %1$s THEN COALESCE(NULLIF(u.capture_date,''),t.capture_date) END AS captureDate,
                       CASE WHEN %1$s THEN COALESCE(NULLIF(u.region,''),t.region) END AS city,
                       CASE WHEN %1$s THEN COALESCE(NULLIF(u.collector,''),t.collector) END AS collector,
                       CASE WHEN %1$s THEN COALESCE(NULLIF(u.device_name,''),t.device_name) END AS device,
                       CASE WHEN %1$s THEN COALESCE(u.task_id,t.task_id) END AS metadataTaskId,
                       CASE WHEN %1$s THEN u.image_folder_name END AS uploadFolder
                %2$s
                LEFT JOIN detection_task u ON t.task_type='OSS_FOLDER' AND t.source_oss_prefix<>'' AND u.id=(
                    SELECT CASE WHEN COUNT(*)=1 THEN MIN(s.id) END FROM detection_task s
                    WHERE s.task_type IN ('BATCH','SINGLE','BATCH_DIRECT') AND BINARY s.source_oss_prefix=BINARY t.source_oss_prefix)
                WHERE t.task_id=:id AND (%3$s OR %1$s)
                """.formatted(readable,SOURCE,UPLOAD_TYPES);
        var rows = db.queryForList(sql,args);
        if (rows.isEmpty()) throw new BusinessException(404,"文件夹登记不存在或无权查看");
        populateUploaderLabels(rows);
        var row = rows.get(0);
        String metadataTaskId = (String) row.remove("metadataTaskId");
        if (metadataTaskId != null) {
            var metadata = uploadMetadata.read(metadataTaskId);
            if (metadata != null) {
                row.put("metadataJson", metadata.document());
                if (metadata.storedInOss()) row.put("metadataOssKey", UploadFolders.metadataKey((String) row.get("prefix")));
            }
        }
        row.put("folder",shortName((String) row.get("folder")));
        row.put("uploadFolder",shortName((String) row.get("uploadFolder")));
        return row;
    }

    private void addMyDetectionTasks(List<Map<String,Object>> uploads, long userId) {
        var byUploadId = new HashMap<String,Map<String,Object>>();
        for (var upload : uploads) byUploadId.put((String) upload.get("taskId"), upload);
        // Folder dispatch uses the full, case-sensitive OSS prefix. Only the signed-in detector's work is eligible.
        String sql = """
            SELECT uploadId, detectionId, detectionStatus FROM (
                SELECT u.task_id AS uploadId, f.task_id AS detectionId, f.status AS detectionStatus,
                       ROW_NUMBER() OVER (PARTITION BY u.task_id ORDER BY
                           CASE WHEN f.status IN ('READY','FAILED') THEN 0
                                WHEN f.status IN ('COMPLETED','PARTIAL_FAILED','CANCELLED') THEN 2 ELSE 1 END,
                           f.created_at DESC, f.id DESC) AS priority
                FROM detection_work_unit w
                JOIN detection_task f ON w.work_unit_id=f.task_id COLLATE utf8mb4_0900_ai_ci AND f.task_type='OSS_FOLDER'
                JOIN detection_task u ON BINARY u.source_oss_prefix=BINARY f.source_oss_prefix
                WHERE w.strategy='OSS_FOLDER' AND w.assignee_user_id=:employeeId
                  AND u.task_id IN (:uploads) AND u.source_oss_prefix<>''
            ) candidates WHERE priority=1
            """;
        var params = new MapSqlParameterSource("employeeId", Long.toString(userId)).addValue("uploads", byUploadId.keySet());
        for (var task : db.queryForList(sql, params)) {
            var upload = byUploadId.get(task.get("uploadId"));
            upload.put("myDetectionTaskId", task.get("detectionId"));
            upload.put("myDetectionStatus", task.get("detectionStatus"));
        }
    }

    public record PageRows(long total, List<Map<String,Object>> items) {}
    private PageRows readPage(String columns, String from, String where, MapSqlParameterSource args, int page, int size) {
        long count = db.queryForObject("SELECT COUNT(*)"+from+where,args,Long.class);
        args.addValue("size",size).addValue("offset",((long)page-1)*size);
        var rows=db.queryForList("SELECT "+columns+from+where+
            " ORDER BY t.created_at DESC,t.id DESC LIMIT :size OFFSET :offset",args);
        return new PageRows(count,rows);
    }

    private void supervisor() {
        if (!users.authenticated().supervisor()) throw new BusinessException(403,"仅主管可管理文件夹派单");
    }
    static void validatePrefix(String prefix) {
        if(prefix==null || !prefix.startsWith("detection/") || !prefix.endsWith("/") || prefix.length()>255 ||
           prefix.chars().anyMatch(Character::isISOControl) || prefix.contains("\\") || prefix.contains("//"))
            throw bad("请选择 detection 下的图片目录");
        for(String part:prefix.split("/")) {
            if(Set.of(".","..","result","results","folder-results").contains(part.toLowerCase(Locale.ROOT))) throw bad("请选择原图目录");
        }
    }
    static boolean imageKey(String key) {
        return key.toLowerCase(Locale.ROOT).matches(".*\\.(jpg|jpeg|png|bmp)$");
    }
    private com.aliyun.oss.model.ObjectListing objects(String prefix,String marker) {
        try { return storage.listFolder(prefix,marker); }
        catch (com.aliyun.oss.OSSException e) { throw new BusinessException(502,"OSS 目录读取失败（"+e.getErrorCode()+"）"); }
        catch (com.aliyun.oss.ClientException | IllegalStateException e) { throw new BusinessException(503,"无法连接 OSS 图片目录"); }
    }
    public Folder folders(String prefix,String marker) {
        supervisor();
        String root=UploadFolders.root(uploadStorage.normalizeBasePrefix());
        if(prefix==null) prefix=root;
        validatePrefix(prefix);
        if(root.equals(prefix)) return new Folder(root,List.of(root+UploadFolders.SUPERVISORS+"/",root+UploadFolders.STAFF+"/"),0,null);
        if(marker!=null && (!marker.startsWith(prefix)||marker.length()>1024)) throw bad("目录分页位置无效");
        var list=objects(prefix,marker);
        var folders=list.getCommonPrefixes().stream().filter(path->{
            try {validatePrefix(path);return true;} catch(BusinessException ignored){return false;}
        }).toList();
        return new Folder(prefix,folders,(int)list.getObjectSummaries().stream().filter(o->imageKey(o.getKey())).count(),
            list.isTruncated()?list.getNextMarker():null);
    }
    private List<String> manifest(String prefix) {
        var keys=new ArrayList<String>();
        String marker=null;
        int pages=0;
        do {
            var list=objects(prefix,marker);
            for (var item:list.getObjectSummaries()) {
                if(!imageKey(item.getKey())) continue;
                if(item.getSize()<=0 || item.getSize()>26_214_400) throw bad("目录包含空图片或超过 25 MB 的图片");
                keys.add(item.getKey());
                if(keys.size()>maxImages) throw bad("单任务最多 "+maxImages+" 张，请选择更小的图片目录");
            }
            marker=list.isTruncated()?list.getNextMarker():null;
            if(++pages>100) throw bad("目录过大，请选择更具体的图片目录");
        } while(marker!=null);
        if(keys.isEmpty()) throw bad("该目录没有直接存放的图片，请选择原图所在的子目录");
        return keys;
    }
    private AgentUserDirectory.Inspector recipient(Recipient value) {
        if(value==null || value.username()==null || value.revision()==null) throw bad("请选择检测员工");
        return employees.lockInspector(new AgentUserDirectory.Inspector(value.userId(),value.username(),value.revision()));
    }
    @Transactional
    public String create(Create request) {
        supervisor();
        if(request==null || request.requestId()==null)throw bad("缺少派单编号");
        validatePrefix(request.prefix());
        String id="det_folder_"+request.requestId().toString().replace("-","");
        return createFolder(id, request.prefix(), users.authenticated(), recipient(request.recipient()), maxImages);
    }

    @Transactional
    public String dispatchApplication(String workUnitId, ApplicationDispatch request) {
        var actor = users.authenticated();
        if (!actor.supervisor()) throw new BusinessException(403,"仅主管可管理文件夹派单");
        if (request == null || request.expectedVersion() == null || request.expectedVersion() < 0
                || request.uploadTaskId() == null || request.uploadTaskId().isBlank() || request.uploadTaskId().length() > 64
                || !workUnitId.matches("WU-[a-f0-9]{32}")) {
            throw bad("请选择上传批次并核对领任务申请版本");
        }
        var jdbc = db.getJdbcTemplate();
        var applications = jdbc.queryForList("""
            SELECT applicant_user_id,assignee_user_id,status,version,image_count,source_batch_id,batch_id
            FROM detection_work_unit WHERE work_unit_id=? AND strategy<>'OSS_FOLDER' FOR UPDATE
            """, workUnitId);
        if (applications.isEmpty()) throw new BusinessException(404, "领任务申请不存在");
        var application = applications.get(0);
        var applicationId = UUID.nameUUIDFromBytes(("folder-application:" + workUnitId).getBytes(StandardCharsets.UTF_8));
        String id = "det_folder_" + applicationId.toString().replace("-", "");
        if (id.equals(application.get("batch_id")) && request.uploadTaskId().equals(application.get("source_batch_id"))) {
            return id;
        }
        String applicant = (String) application.get("applicant_user_id");
        Object assignee = application.get("assignee_user_id");
        String status = (String) application.get("status");
        boolean assignable = ("WAITING".equals(status) && assignee == null)
                || ("ASSIGNED".equals(status) && applicant.equals(assignee));
        if (!assignable || application.get("batch_id") != null || application.get("source_batch_id") != null
                || !request.expectedVersion().equals(((Number) application.get("version")).intValue())
                || Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM detection_input WHERE work_unit_id=?)", Boolean.class, workUnitId))) {
            throw new BusinessException(409, "领任务申请已变化或已有图片，请刷新核对");
        }
        var employee = employees.lockInspector(employees.inspector(applicant));
        var uploads = jdbc.queryForList("""
            SELECT task_id,source_oss_prefix FROM detection_task
            WHERE task_id=? AND task_type IN ('BATCH','BATCH_DIRECT')
              AND status NOT IN ('UPLOADING','CANCELLED') AND total_images>0 FOR UPDATE
            """, request.uploadTaskId());
        if (uploads.isEmpty()) throw new BusinessException(409, "上传批次已变化或图片尚未上传完成");
        var upload = uploads.get(0);
        String prefix = (String) upload.get("source_oss_prefix");
        validatePrefix(prefix);
        if (!jdbc.queryForList("""
            SELECT id FROM detection_task WHERE task_type='OSS_FOLDER' AND status<>'CANCELLED'
              AND source_oss_prefix=? AND BINARY source_oss_prefix=BINARY ? LIMIT 1 FOR UPDATE
            """, prefix, prefix).isEmpty()) {
            throw new BusinessException(409, "此批次已派单，请选择其他上传批次");
        }
        int requestedCount = ((Number) application.get("image_count")).intValue();
        createFolder(id, prefix, actor, employee, requestedCount);
        jdbc.update("""
            UPDATE detection_work_unit SET source_batch_id=?,batch_id=?,assignee_user_id=?,assigned_user_name=?,
              status='ASSIGNED',assigned_at=COALESCE(assigned_at,NOW()),version=version+1 WHERE work_unit_id=?
            """, upload.get("task_id"), id, employee.username(), employee.username(), workUnitId);
        workUnitAudit.record(actor, "DETECTION_APPLICATION_APPROVED", workUnitId, applicationId.toString(),
                request.expectedVersion().longValue() + 1);
        return id;
    }

    private String createFolder(String id, String prefix, BusinessUserDirectory.Identity actor,
                                AgentUserDirectory.Inspector employee, int requestedCount) {
        var jdbc=db.getJdbcTemplate();
        // A retry reuses the same work unit and never replaces its original manifest.
        jdbc.update("""
            INSERT INTO detection_work_unit(work_unit_id,applicant_user_id,assignee_user_id,assigned_user_name,
              strategy,status,image_count,assigned_at) VALUES(?,?,?,?,'OSS_FOLDER','ASSIGNED',0,NOW())
              ON DUPLICATE KEY UPDATE id=id
            """, id,Long.toString(actor.userId()),Long.toString(employee.userId()),employee.username());
        var prior=jdbc.queryForList("SELECT source_oss_prefix,created_by FROM detection_task WHERE task_id=? FOR UPDATE",id);
        if(!prior.isEmpty()) {
            var row=prior.get(0);
            if(!prefix.equals(row.get("source_oss_prefix")) || !actor.username().equals(row.get("created_by")) ||
                !Long.toString(employee.userId()).equals(jdbc.queryForObject("SELECT assignee_user_id FROM detection_work_unit WHERE work_unit_id=?",String.class,id)))
                throw new BusinessException(409,"派单编号已使用，请刷新");
            return id;
        }
        var keys=manifest(prefix);
        if (keys.size() > requestedCount) throw bad("原图批次的图片数量超过申请上限，请选择较小的批次");
        detection.registerFolder(id,prefix,keys,actor.username());
        jdbc.update("UPDATE detection_work_unit SET image_count=? WHERE work_unit_id=?",keys.size(),id);
        workUnitAudit.record(actor, "DETECTION_FOLDER_ASSIGNED", id, id, 0);
        return id;
    }
    @Transactional
    public void assign(String id,Assign request) {
        var actor = users.authenticated();
        if (!actor.supervisor()) throw new BusinessException(403,"仅主管可管理文件夹派单");
        var to=recipient(request.recipient());
        int changed=db.getJdbcTemplate().update("""
            UPDATE detection_work_unit SET assignee_user_id=?,assigned_user_name=?,assigned_at=NOW(),version=version+1
            WHERE work_unit_id=? AND strategy='OSS_FOLDER' AND status='ASSIGNED' AND version=?
            """,Long.toString(to.userId()),to.username(),id,request.version());
        if(changed!=1) throw new BusinessException(409,"任务已经启动或分派已变化，请刷新");
        workUnitAudit.record(actor, "DETECTION_FOLDER_REASSIGNED", id, id + ":" + request.version(), request.version() + 1L);
    }
    @Transactional
    public void start(String id,int version) {
        var actor=users.authenticated();
        var jdbc=db.getJdbcTemplate();
        var rows=jdbc.queryForList("SELECT * FROM detection_work_unit WHERE work_unit_id=? AND strategy='OSS_FOLDER' AND assignee_user_id=? FOR UPDATE",id,Long.toString(actor.userId()));
        if(rows.isEmpty())throw new BusinessException(403,"仅受派检测员工可启动模型");
        var unit=rows.get(0);
        if(((Number)unit.get("version")).intValue()!=version)throw new BusinessException(409,"任务已更新，请刷新");
        detection.dispatchAssignedFolder(id);
        jdbc.update("UPDATE detection_work_unit SET status='PROCESSING',submitted_at=NOW(),completed_at=NULL,completed_count=0,assigned_user_name=?,version=version+1 WHERE work_unit_id=?",actor.username(),id);
    }
    private static BusinessException bad(String reason){return new BusinessException(400,reason);}
}
