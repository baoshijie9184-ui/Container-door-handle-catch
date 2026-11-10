package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.contracts.collaboration.ChangeHistory;
import com.ruanzhu.doorhandle.contracts.collaboration.SystemChangeAuditApi;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Automatic execution facts. User identity/permission checks never govern worker completion. */
@Service
public class DetectionSystemChanges {
    public static final class HistoryFailure extends RuntimeException {
        public HistoryFailure(String message,Throwable cause){super(message,cause);}
    }
    private static final Set<String> TERMINAL=Set.of("COMPLETED","PARTIAL_FAILED","FAILED","CANCELLED");
    private static final String SELECT="SELECT task_id,version,dispatch_id,created_user_id,created_identity_name,created_by,"
            +"status,stage,flow_status,total_images,processed_images,successful_images,failed_images,defect_count,primary_defect_type,max_defect_severity,"
            +"review_status,started_at,finished_at,"
            +"(result_json_oss_key IS NOT NULL OR result_oss_prefix IS NOT NULL) AS result_present,"
            +"SHA2(statistics_json,256) AS statistics_sha256,SHA2(defect_evidence_json,256) AS defect_evidence_sha256,"
            +"SHA2(error_message,256) AS error_sha256 FROM detection_task WHERE task_id=?";
    private static final List<String> FIELDS=List.of("status","stage","flow_status","total_images","processed_images","successful_images","failed_images",
            "defect_count","primary_defect_type","max_defect_severity","review_status","started_at","finished_at","result_present","statistics_sha256","defect_evidence_sha256","error_sha256");
    private static final Map<String,String> LABELS=Map.ofEntries(Map.entry("status","检测状态"),Map.entry("stage","执行阶段"),Map.entry("flow_status","业务流程"),
            Map.entry("total_images","图片总数"),Map.entry("processed_images","已处理图片"),Map.entry("successful_images","成功图片"),Map.entry("failed_images","失败图片"),
            Map.entry("defect_count","缺陷数量"),Map.entry("primary_defect_type","主要缺陷"),Map.entry("max_defect_severity","最高缺陷级别"),Map.entry("review_status","复核状态"),
            Map.entry("started_at","开始时间"),Map.entry("finished_at","结束时间"),Map.entry("result_present","结果已登记"),Map.entry("statistics_sha256","统计摘要指纹"),
            Map.entry("defect_evidence_sha256","缺陷证据指纹"),Map.entry("error_sha256","错误信息指纹"));
    public record Snapshot(String taskId,long version,String dispatchId,Map<String,Object> fields,SystemChangeAuditApi.Initiator initiator) {
        public Snapshot { fields=Collections.unmodifiableMap(new LinkedHashMap<>(fields)); }
    }
    private final JdbcTemplate jdbc;
    private SystemChangeAuditApi audit;
    @Value("${collaboration.change-history.enabled:false}") private boolean history;
    @Value("${collaboration.mutations.enabled:false}") private boolean mutations;
    public DetectionSystemChanges(JdbcTemplate jdbc){this.jdbc=jdbc;}
    @Autowired(required=false) public void audit(SystemChangeAuditApi value){audit=value;}
    private boolean enabled(){return history||mutations;}

    @Transactional(propagation=Propagation.MANDATORY)
    public Snapshot before(String taskId){return enabled()?read(taskId,true):null;}

    @Transactional(propagation=Propagation.MANDATORY)
    public void record(Snapshot before,SystemChangeAuditApi.Component component,String sourceEventId,String action,DetectionTask returned){
        if(before==null)return;
        var after=read(before.taskId(),false);var changes=new ArrayList<ChangeHistory.Change>();
        for(String field:FIELDS){Object previous=before.fields().get(field),current=after.fields().get(field);
            if(!Objects.equals(previous,current))changes.add(new ChangeHistory.Change(field,LABELS.get(field),"REPLACE",previous,current,null,false));}
        if(changes.isEmpty())return;
        if(audit==null)throw new HistoryFailure("System execution change audit is required",null);
        long next=Math.incrementExact(before.version());
        if(after.version()!=before.version()||jdbc.update("UPDATE detection_task SET version=? WHERE task_id=? AND version=?",next,before.taskId(),before.version())!=1)
            throw new IllegalStateException("System execution revision changed while locked");
        String identity=sourceEventId==null||!sourceEventId.matches("[A-Za-z0-9_:./-]{1,128}")?eventId(component,before.taskId(),before.dispatchId(),action):sourceEventId;
        try{audit.appendSystemChange(new SystemChangeAuditApi.Event(component,identity,before.initiator(),"DETECTION","DETECTION_TASK",before.taskId(),action,identity,before.version(),next,changes));}
        catch(RuntimeException failure){throw new HistoryFailure("System execution audit rejected the transaction",failure);}
        if(returned!=null)returned.setVersion(next);
    }
    @Transactional(propagation=Propagation.MANDATORY)
    public void createdCompleted(DetectionTask task){
        if(!enabled())return;
        var current=read(task.getTaskId(),true);
        if(!"COMPLETED".equals(current.fields().get("status")))throw new IllegalStateException("New inference result is not complete");
        var changes=new ArrayList<ChangeHistory.Change>();
        for(String field:FIELDS){Object value=current.fields().get(field);if(value!=null)changes.add(new ChangeHistory.Change(field,LABELS.get(field),"ADD",null,value,null,false));}
        String identity=eventId(SystemChangeAuditApi.Component.IMAGE_DETECTION,current.taskId(),current.dispatchId(),"SYSTEM_COMPLETED");
        if(audit==null)throw new HistoryFailure("System execution change audit is required",null);
        try{audit.appendSystemChange(new SystemChangeAuditApi.Event(SystemChangeAuditApi.Component.IMAGE_DETECTION,identity,current.initiator(),
                "DETECTION","DETECTION_TASK",current.taskId(),"SYSTEM_COMPLETED",identity,null,current.version(),changes));}
        catch(RuntimeException failure){throw new HistoryFailure("System execution audit rejected the transaction",failure);}
        task.setVersion(current.version());
    }

    private Snapshot read(String taskId,boolean lock){
        if(taskId==null||!taskId.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("Invalid system task identity");
        var rows=jdbc.queryForList(SELECT+(lock?" FOR UPDATE":""),taskId);
        if(rows.size()!=1)throw new IllegalStateException("System task no longer exists");
        var row=rows.get(0);if(!(row.get("version") instanceof Number version)||version.longValue()<0)throw new IllegalStateException("System task revision unavailable");
        var fields=new LinkedHashMap<String,Object>();
        for(String field:FIELDS){Object value=row.get(field);if(value instanceof java.sql.Timestamp time)value=time.toLocalDateTime().toString();
            else if(value instanceof java.time.temporal.TemporalAccessor time)value=time.toString();
            if(value instanceof String text&&text.length()>512)value="sha256:"+digest(text);fields.put(field,value);}
        Long userId=row.get("created_user_id") instanceof Number id?id.longValue():null;
        String username=Objects.toString(row.get("created_identity_name"),Objects.toString(row.get("created_by"),null));
        if(username!=null&&(username.isBlank()||username.length()>128))username=null;
        var initiator=userId==null&&username==null?null:new SystemChangeAuditApi.Initiator(userId,username);
        return new Snapshot(taskId,version.longValue(),(String)row.get("dispatch_id"),fields,initiator);
    }

    @Transactional
    public boolean startLocal(DetectionTask original){
        var before=read(original.getTaskId(),true);
        if(!Objects.equals(before.dispatchId(),original.getDispatchId())||!"QUEUED".equals(before.fields().get("status")))return false;
        jdbc.update("UPDATE detection_task SET status='PROCESSING',stage='PROCESSING',started_at=COALESCE(started_at,CURRENT_TIMESTAMP),updated_at=CURRENT_TIMESTAMP WHERE task_id=?",before.taskId());
        record(enabled()?before:null,SystemChangeAuditApi.Component.IMAGE_DETECTION_ASYNC,null,"SYSTEM_STARTED",original);
        return true;
    }

    @Transactional
    public boolean finishLocal(DetectionTask output){
        var before=read(output.getTaskId(),true);
        if(!Objects.equals(before.dispatchId(),output.getDispatchId())||!"PROCESSING".equals(before.fields().get("status")))return false;
        jdbc.update("UPDATE detection_task SET status='COMPLETED',stage='COMPLETED',statistics_json=?,processed_images=?,successful_images=?,failed_images=?,finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE task_id=?",
                output.getStatisticsJson(),output.getProcessedImages(),output.getSuccessfulImages(),output.getFailedImages(),before.taskId());
        record(enabled()?before:null,SystemChangeAuditApi.Component.IMAGE_DETECTION_ASYNC,null,"SYSTEM_COMPLETED",output);
        return true;
    }

    @Transactional
    public boolean failLocal(DetectionTask original,String error){
        var before=read(original.getTaskId(),true);
        if(!Objects.equals(before.dispatchId(),original.getDispatchId())||TERMINAL.contains(Objects.toString(before.fields().get("status"),"")))return false;
        jdbc.update("UPDATE detection_task SET status='FAILED',stage='FAILED',flow_status='FAILED',error_message=?,finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE task_id=?",error,before.taskId());
        record(enabled()?before:null,SystemChangeAuditApi.Component.IMAGE_DETECTION_ASYNC,null,"SYSTEM_FAILED",original);
        return true;
    }
    public static String eventId(SystemChangeAuditApi.Component component,String taskId,String dispatch,String action){return "system:"+digest(component.name()+"\n"+taskId+"\n"+Objects.toString(dispatch,"")+"\n"+action);}
    private static String digest(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
}
