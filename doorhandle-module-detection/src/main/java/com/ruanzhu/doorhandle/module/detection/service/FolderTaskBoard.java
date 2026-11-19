package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.impl.DetectionTaskServiceImpl;
import com.ruanzhu.doorhandle.module.infra.service.OssPreviewStorage;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;

@Service
@RequiredArgsConstructor
public class FolderTaskBoard {
    public record Recipient(String username, long userId, String revision) {}
    public record Create(UUID requestId, String prefix, Recipient recipient) {}
    public record Assign(int version, Recipient recipient) {}
    public record Folder(String prefix, List<String> folders, int imagesOnPage, String next) {}

    private final NamedParameterJdbcTemplate db;
    private final OssPreviewStorage storage;
    private final DetectionTaskServiceImpl detection;
    private final DetectionTaskAccessPolicy access;
    private final BusinessUserDirectory users;
    private final AgentUserDirectory employees;
    @Value("${detection.max-images-per-batch:200}") private int maxImages;

    private static final String PHASE = """
        CASE WHEN t.status IN ('FAILED','CANCELLED') THEN 'FAILED'
             WHEN t.flow_status IN ('RECHECK_REQUIRED','REWORK_REQUIRED','HOLD') THEN 'VERIFYING'
             WHEN t.reviewed_at IS NOT NULL AND t.review_status='REVIEWED' THEN 'DONE'
             WHEN t.status IN ('COMPLETED','PARTIAL_FAILED') THEN 'VERIFYING'
             WHEN t.status IN ('READY','UPLOADING','UPLOADED','PENDING') THEN 'READY'
             ELSE 'DETECTING' END
        """;
    private static final String SOURCE = " FROM detection_task t LEFT JOIN detection_work_unit w ON w.work_unit_id=t.task_id AND w.strategy='OSS_FOLDER' ";
    private static final String COLUMNS = """
        t.task_id AS taskId,t.task_type AS taskType,t.image_folder_name AS folder,t.source_oss_prefix AS prefix,
        t.model_version AS model,t.status AS modelStatus,t.flow_status AS flow,t.review_status AS reviewStatus,
        t.total_images AS totalImages,t.processed_images AS processedImages,t.failed_images AS failedImages,
        t.assignee AS qualityAssignee,t.reviewer AS qualityOperator,t.reviewed_at AS reviewedAt,
        w.assigned_user_name AS detector,w.version AS assignmentVersion,
        CASE WHEN w.submitted_at IS NOT NULL AND t.status IN ('COMPLETED','PARTIAL_FAILED') THEN w.assigned_user_name END AS detectionOperator,
        CASE WHEN w.assignee_user_id=CAST(:actor AS CHAR) THEN 1 ELSE 0 END AS mine,
        t.created_at AS createdAt
        """;

    public Map<String,Object> list(String phase, String keyword, boolean inbox, int page, int size) {
        var actor = users.authenticated();
        var scope = access.currentSqlScope("t.");
        var args = new MapSqlParameterSource(scope.parameters()).addValue("actor",actor.userId());
        String where = " WHERE ("+scope.predicate()+" OR w.assignee_user_id=CAST(:actor AS CHAR))";
        if(inbox) {
            where += """
              AND ((w.assignee_user_id=CAST(:actor AS CHAR) AND t.status IN ('READY','FAILED'))
                OR (t.assignee=:username AND (t.assignee_user_id IS NULL OR t.assignee_user_id=:actor)
                AND t.flow_status IN ('PENDING_REVIEW','REVIEWING') AND t.review_status='PENDING'))
              """;
            args.addValue("username",actor.username());
        }
        if (phase != null && !phase.isBlank()) {
            if (!Set.of("READY","DETECTING","VERIFYING","DONE","FAILED").contains(phase)) throw bad("未知任务阶段");
            where += " AND ("+PHASE+")=:phase"; args.addValue("phase",phase);
        }
        if (keyword != null && !keyword.isBlank()) {
            if(keyword.length()>255) throw bad("搜索内容过长");
            where+=" AND (LOCATE(:q,t.task_id)>0 OR LOCATE(:q,t.image_folder_name)>0 OR LOCATE(:q,t.source_oss_prefix)>0 OR LOCATE(:q,w.assigned_user_name)>0 OR LOCATE(:q,t.assignee)>0 OR LOCATE(:q,t.reviewer)>0)";
            args.addValue("q",keyword.strip());
        }
        long count = db.queryForObject("SELECT COUNT(*)"+SOURCE+where,args,Long.class);
        args.addValue("size",size).addValue("offset",((long)page-1)*size);
        var rows=db.queryForList("SELECT "+COLUMNS+", "+PHASE+" AS phase"+SOURCE+where+
            " ORDER BY t.created_at DESC,t.id DESC LIMIT :size OFFSET :offset",args);
        return Map.of("total",count,"items",rows);
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
        supervisor(); validatePrefix(prefix);
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
        var actor=users.authenticated();
        var employee=recipient(request.recipient());
        String id="det_folder_"+request.requestId().toString().replace("-","");
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
            if(!request.prefix().equals(row.get("source_oss_prefix")) || !actor.username().equals(row.get("created_by")) ||
                !Long.toString(employee.userId()).equals(jdbc.queryForObject("SELECT assignee_user_id FROM detection_work_unit WHERE work_unit_id=?",String.class,id)))
                throw new BusinessException(409,"派单编号已使用，请刷新");
            return id;
        }
        var keys=manifest(request.prefix());
        detection.registerFolder(id,request.prefix(),keys,actor.username());
        jdbc.update("UPDATE detection_work_unit SET image_count=? WHERE work_unit_id=?",keys.size(),id);
        return id;
    }
    @Transactional
    public void assign(String id,Assign request) {
        supervisor(); var to=recipient(request.recipient());
        int changed=db.getJdbcTemplate().update("""
            UPDATE detection_work_unit SET assignee_user_id=?,assigned_user_name=?,assigned_at=NOW(),version=version+1
            WHERE work_unit_id=? AND strategy='OSS_FOLDER' AND status='ASSIGNED' AND version=?
            """,Long.toString(to.userId()),to.username(),id,request.version());
        if(changed!=1) throw new BusinessException(409,"任务已经启动或分派已变化，请刷新");
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
        jdbc.update("UPDATE detection_work_unit SET status='PROCESSING',submitted_at=NOW(),assigned_user_name=?,version=version+1 WHERE work_unit_id=?",actor.username(),id);
    }
    private static BusinessException bad(String reason){return new BusinessException(400,reason);}
}
