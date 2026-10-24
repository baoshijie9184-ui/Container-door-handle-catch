package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import java.nio.ByteBuffer;
import java.security.MessageDigest;
import java.time.*;
import java.util.*;

/** Bounded consistent-snapshot report. Never repairs identities or grants permission. */
@Service
@ConditionalOnProperty(prefix="detection.identity",name="reconciliation-enabled",havingValue="true")
public class DetectionIdentityReconciliationService {
    private static final String PROTOCOL="identity-reconciliation-v1";
    private static final ZoneOffset ZONE=ZoneOffset.ofHours(8);
    private static final SortedMap<String,String> ROLES=new TreeMap<>(Map.of("created","created_by","assignee","assignee",
            "reviewer","reviewer","disposition","disposition_operator","rework","rework_operator"));
    private static final Set<String> REASONS=Set.of("MISSING_NAME","UNMAPPED","INVALID_ID","SNAPSHOT_MISMATCH",
            "ACCOUNT_UNAVAILABLE","STALE_BINDING","SOURCE_UNVERIFIED","SOURCE_INVALID","SOURCE_MISMATCH");
    private static final String FIELDS="task_id,created_by,assignee,reviewer,disposition_operator,rework_operator,"
            +"created_user_id,assignee_user_id,reviewer_user_id,disposition_user_id,rework_user_id,"
            +"created_identity_name,assignee_identity_name,reviewer_identity_name,disposition_identity_name,rework_identity_name";
    private final JdbcTemplate jdbc;private final BusinessUserDirectory users;private final BusinessAccountLookupApi accounts;
    private final DetectionIdentityEvidenceService evidence;private final OperationsAuditApi audit;private final ObjectMapper json;
    @Value("${detection.identity.reconciliation-max-tasks:20000}") private int maxTasks;
    @Value("${detection.identity.reconciliation-max-reports:20}") private int maxReports;
    public DetectionIdentityReconciliationService(JdbcTemplate jdbc,BusinessUserDirectory users,BusinessAccountLookupApi accounts,
            DetectionIdentityEvidenceService evidence,OperationsAuditApi audit,ObjectMapper json){
        this.jdbc=jdbc;this.users=users;this.accounts=accounts;this.evidence=evidence;this.audit=audit;this.json=json;
    }
    @jakarta.annotation.PostConstruct public void schema(){
        if(maxTasks<1||maxTasks>20000||maxReports<1||maxReports>100)throw new IllegalStateException("身份核对报告配额无效");
        jdbc.queryForList("SELECT id,request_id,actor_user_id,actor_name,request_sha256,protocol,control_revision,identity_mode,source_mode,started_at,finished_at,task_count,role_count,issue_count,dataset_sha256,previous_report_id,summary_json FROM detection_identity_reconciliation_report WHERE 1=0");
        jdbc.queryForList("SELECT id,report_id,task_id,identity_role,existing_name,existing_user_id,identity_name,current_username,current_role,current_revision,source_kind,source_request_id,source_sha256,reason_codes,item_sha256 FROM detection_identity_reconciliation_item WHERE 1=0");
    }
    public record Create(String requestId,Long revision,Boolean sourceProtection){}
    private AgentActor supervisor(AgentActor actor,boolean lock){
        var current=lock?users.lockCurrent(actor.userId(),actor.username()):users.current(actor.userId(),actor.username());
        if(!current.supervisor())throw new SecurityException("仅主管可核对企业任务身份");
        return new AgentActor(current.userId(),current.username(),AgentActor.Role.SUPERVISOR);
    }
    @Transactional(propagation=Propagation.REQUIRES_NEW,isolation=Isolation.REPEATABLE_READ,timeout=30)
    public Map<String,Object> create(AgentActor actor,Create command){
        var current=supervisor(actor,true);
        if(command==null||!request(command.requestId())||command.revision()==null||command.revision()<0||!Boolean.TRUE.equals(command.sourceProtection()))throw bad(400,"核对报告需要原请求编号、预览版本和来源范围");
        LocalDateTime started=LocalDateTime.now(ZONE);
        var control=jdbc.queryForMap("SELECT mode,revision FROM detection_identity_control WHERE control_id=1 FOR UPDATE");
        String requestDigest=hash(Map.of("protocol",PROTOCOL,"revision",command.revision(),"sourceProtection",true));
        var existing=jdbc.queryForList("SELECT * FROM detection_identity_reconciliation_report WHERE request_id=?",command.requestId());
        if(!existing.isEmpty()){
            var row=existing.get(0);if(number(row.get("actor_user_id"))!=current.userId()||!requestDigest.equals(row.get("request_sha256")))throw bad(409,"核对请求编号已用于其他范围或账号");
            return receipt(row,true);
        }
        long revision=((Number)control.get("revision")).longValue();
        if(revision!=command.revision())throw bad(409,"预览版本已变化，请重新预览再生成核对摘要");
        String mode=Objects.toString(control.get("mode"),"");if(!Set.of("PREVIEW","ACTIVE").contains(mode))throw bad(503,"身份授权模式未能核对");
        String sourceMode=evidence.active()?"ACTIVE":"COLLECTING";
        if(sourceMode.equals("ACTIVE")&&!mode.equals("ACTIVE"))throw bad(503,"身份授权与来源模式不一致");
        long total=jdbc.queryForObject("SELECT COUNT(*) FROM detection_task",Long.class);
        if(total>maxTasks)throw bad(413,"任务量超过单次一致快照报告上限，未生成部分报告");
        if(jdbc.queryForObject("SELECT COUNT(*) FROM detection_identity_reconciliation_report",Long.class)>=maxReports)throw bad(409,"核对报告已达到保存上限，请先按运维流程归档");
        var previous=jdbc.queryForList("SELECT id,request_id,dataset_sha256,task_count,issue_count FROM detection_identity_reconciliation_report WHERE protocol=? ORDER BY id DESC LIMIT 1",PROTOCOL);
        Long previousId=previous.isEmpty()?null:number(previous.get(0).get("id"));
        var stats=new TreeMap<String,Object>();stats.put("protocol",PROTOCOL);stats.put("scope","ENTERPRISE");stats.put("isolation","REPEATABLE_READ");
        // The placeholder belongs only to this uncommitted transaction. Every row is rolled back on failure.
        jdbc.update("INSERT INTO detection_identity_reconciliation_report(request_id,actor_user_id,actor_name,request_sha256,protocol,control_revision,identity_mode,source_mode,started_at,finished_at,task_count,role_count,issue_count,dataset_sha256,previous_report_id,summary_json) VALUES(?,?,?,?,?,?,?,?,?,?,0,0,0,?,?,?)",
                command.requestId(),current.userId(),current.username(),requestDigest,PROTOCOL,revision,mode,sourceMode,started,started,"0".repeat(64),previousId,"{}");
        long report=jdbc.queryForObject("SELECT id FROM detection_identity_reconciliation_report WHERE request_id=?",Long.class,command.requestId());
        var digest=digest();feed(digest,Map.of("datasetProtocol","identity-dataset-v1","tasks",total));
        var cached=new HashMap<Long,BusinessAccountLookupApi.Account>();var missing=new HashSet<Long>();
        var reasonCounts=new TreeMap<String,Long>();for(String reason:REASONS)reasonCounts.put(reason,0L);
        String cursor="";long taskCount=0,roleCount=0,issueCount=0,requiredIssues=0;
        while(true){
            var page=jdbc.queryForList("SELECT "+FIELDS+" FROM detection_task WHERE task_id>? ORDER BY task_id LIMIT 100",cursor);
            if(page.isEmpty())break;
            var sources=evidence.sources(page.stream().map(row->row.get("task_id").toString()).toList());
            var issueWrites=new ArrayList<Object[]>();
            for(var task:page){
                String taskId=task.get("task_id").toString();taskCount++;
                for(var entry:ROLES.entrySet()){
                    String role=entry.getKey();String name=Objects.toString(task.get(entry.getValue()),"");Long id=number(task.get(role+"_user_id"));
                    String snapshot=(String)task.get(role+"_identity_name");
                    var source=sources.getOrDefault(taskId,Map.of()).getOrDefault(role,Map.of("state","SOURCE_UNVERIFIED"));
                    BusinessAccountLookupApi.Account account=null;
                    if(id!=null&&id>0){if(!cached.containsKey(id)&&!missing.contains(id)){var value=accounts.describe(id);if(value==null)missing.add(id);else cached.put(id,value);}account=cached.get(id);}
                    var reasons=classify(role,name,id,snapshot,account,source);
                    var material=new TreeMap<String,Object>();material.put("task",taskId);material.put("role",role);material.put("name",name);material.put("userId",id);material.put("identityName",snapshot);material.put("account",account);material.put("source",source);material.put("reasons",reasons);
                    feed(digest,material);roleCount++;
                    if(!reasons.isEmpty()){
                        issueCount++;if(role.equals("created")||role.equals("assignee"))requiredIssues++;
                        for(String reason:reasons)reasonCounts.compute(reason,(key,value)->value+1);
                        issueWrites.add(new Object[]{report,taskId,role,name,id,snapshot,account==null?null:account.username(),account==null?null:account.role(),account==null?null:account.revision(),source.get("source_kind"),source.get("request_id"),source.get("event_sha256"),encode(reasons),hash(material)});
                    }
                }
            }
            if(!issueWrites.isEmpty()){
                int[] counts=jdbc.batchUpdate("INSERT INTO detection_identity_reconciliation_item(report_id,task_id,identity_role,existing_name,existing_user_id,identity_name,current_username,current_role,current_revision,source_kind,source_request_id,source_sha256,reason_codes,item_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",issueWrites);
                if(counts.length!=issueWrites.size()||Arrays.stream(counts).anyMatch(count->count!=1&&count!=java.sql.Statement.SUCCESS_NO_INFO))throw bad(503,"核对明细写入未确认，停止保存整批报告");
            }
            cursor=page.get(page.size()-1).get("task_id").toString();
        }
        if(taskCount!=total||taskCount>maxTasks||roleCount!=taskCount*ROLES.size())throw bad(503,"快照遍历数量不一致，未保存核对报告");
        String datasetDigest=HexFormat.of().formatHex(digest.digest());
        stats.put("reasonCounts",reasonCounts);stats.put("requiredRoleIssueRows",requiredIssues);
        stats.put("sourceEventHighWater",jdbc.queryForObject("SELECT COALESCE(MAX(id),0) FROM detection_identity_binding_event",Long.class));
        stats.put("comparison",comparison(report,issueCount,previous));stats.put("datasetChanged",previous.isEmpty()?"UNKNOWN":datasetDigest.equals(previous.get(0).get("dataset_sha256"))?"UNCHANGED":"CHANGED");
        LocalDateTime finished=LocalDateTime.now(ZONE);
        if(jdbc.update("UPDATE detection_identity_reconciliation_report SET finished_at=?,task_count=?,role_count=?,issue_count=?,dataset_sha256=?,summary_json=? WHERE id=?",finished,taskCount,roleCount,issueCount,datasetDigest,encode(stats),report)!=1)throw bad(503,"核对摘要保存未确认");
        audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","DETECTION_IDENTITY","RECONCILE_SNAPSHOT",command.requestId(),command.requestId(),"OBSERVED",revision));
        return receipt(jdbc.queryForMap("SELECT * FROM detection_identity_reconciliation_report WHERE id=?",report),false);
    }
    private List<String> classify(String role,String name,Long id,String snapshot,BusinessAccountLookupApi.Account account,Map<String,Object> source){
        var result=new TreeSet<String>();
        if(name.isBlank()){
            if(Boolean.TRUE.equals(source.get("missing_name_confirmed"))&&"SOURCE_RECORDED".equals(source.get("state"))&&"SUPERVISOR_MISSING_NAME".equals(source.get("source_kind"))&&Objects.equals(id,number(source.get("bound_user_id")))&&name.equals(snapshot)&&name.equals(source.get("bound_identity_name"))){
                if(id==null||id<1)result.add("INVALID_ID");else if(account==null)result.add("ACCOUNT_UNAVAILABLE");
                return List.copyOf(result);
            }
            if(role.equals("created"))result.add("MISSING_NAME");
            if(id!=null||snapshot!=null)result.add("STALE_BINDING");
            if(source.containsKey("source_kind")&&!"OBSERVED_CLEAR".equals(source.get("source_kind")))result.add("SOURCE_MISMATCH");
            return List.copyOf(result);
        }
        if(id==null)result.add("UNMAPPED");else if(id<1)result.add("INVALID_ID");else if(account==null)result.add("ACCOUNT_UNAVAILABLE");
        if(!name.equals(snapshot))result.add("SNAPSHOT_MISMATCH");
        if(!source.containsKey("source_kind"))result.add("SOURCE_UNVERIFIED");
        else if("OBSERVED_CLEAR".equals(source.get("source_kind")))result.add("SOURCE_MISMATCH");
        else if(!"SOURCE_RECORDED".equals(source.get("state")))result.add("SOURCE_INVALID");
        else if(!Objects.equals(id,number(source.get("bound_user_id")))||!name.equals(source.get("bound_identity_name")))result.add("SOURCE_MISMATCH");
        return List.copyOf(result);
    }
    private Map<String,Object> comparison(long report,long issueCount,List<Map<String,Object>> previous){
        if(previous.isEmpty())return Map.of("available",false);
        long before=((Number)previous.get(0).get("id")).longValue();
        long added=jdbc.queryForObject("SELECT COUNT(*) FROM detection_identity_reconciliation_item c LEFT JOIN detection_identity_reconciliation_item p ON p.report_id=? AND p.task_id=c.task_id AND p.identity_role=c.identity_role WHERE c.report_id=? AND p.id IS NULL",Long.class,before,report);
        long changed=jdbc.queryForObject("SELECT COUNT(*) FROM detection_identity_reconciliation_item c JOIN detection_identity_reconciliation_item p ON p.report_id=? AND p.task_id=c.task_id AND p.identity_role=c.identity_role WHERE c.report_id=? AND c.item_sha256<>p.item_sha256",Long.class,before,report);
        long unchanged=jdbc.queryForObject("SELECT COUNT(*) FROM detection_identity_reconciliation_item c JOIN detection_identity_reconciliation_item p ON p.report_id=? AND p.task_id=c.task_id AND p.identity_role=c.identity_role WHERE c.report_id=? AND c.item_sha256=p.item_sha256",Long.class,before,report);
        long notObserved=jdbc.queryForObject("SELECT COUNT(*) FROM detection_identity_reconciliation_item p LEFT JOIN detection_identity_reconciliation_item c ON c.report_id=? AND c.task_id=p.task_id AND c.identity_role=p.identity_role WHERE p.report_id=? AND c.id IS NULL",Long.class,report,before);
        if(added+changed+unchanged!=issueCount||notObserved+changed+unchanged!=((Number)previous.get(0).get("issue_count")).longValue())throw bad(503,"核对比较数量不一致，停止保存报告");
        return Map.of("available",true,"previousRequestId",previous.get(0).get("request_id"),"previousDatasetDigest",previous.get(0).get("dataset_sha256"),"newIssueRows",added,"changedIssueRows",changed,"unchangedIssueRows",unchanged,"previousIssuesNotObserved",notObserved);
    }
    @Transactional(readOnly=true)
    public Map<String,Object> status(AgentActor actor,String requestId){
        supervisor(actor,false);if(!request(requestId))throw bad(400,"核对请求编号无效");
        var rows=jdbc.queryForList("SELECT * FROM detection_identity_reconciliation_report WHERE request_id=?",requestId);
        return rows.isEmpty()?Map.of("requestId",requestId,"found",false,"state","NOT_RECORDED_YET"):receipt(rows.get(0),false);
    }
    @Transactional(readOnly=true)
    public Map<String,Object> items(AgentActor actor,String requestId,long after,int size){
        supervisor(actor,false);if(!request(requestId)||after<0||size<1||size>100)throw bad(400,"核对明细分页无效");
        var reports=jdbc.queryForList("SELECT id FROM detection_identity_reconciliation_report WHERE request_id=?",requestId);
        if(reports.isEmpty())throw bad(404,"尚未查到已提交的核对报告");
        var rows=jdbc.queryForList("SELECT id,task_id,identity_role,existing_name,existing_user_id,identity_name,current_username,current_role,current_revision,source_kind,source_request_id,source_sha256,reason_codes,item_sha256 FROM detection_identity_reconciliation_item WHERE report_id=? AND id>? ORDER BY id LIMIT ?",reports.get(0).get("id"),after,size);
        var records=new ArrayList<Map<String,Object>>();
        for(var row:rows){var item=new LinkedHashMap<>(row);try{List<String> reasons=json.readValue(row.get("reason_codes").toString(),new TypeReference<List<String>>(){});if(reasons.isEmpty()||!REASONS.containsAll(reasons))throw new IllegalStateException();item.remove("reason_codes");item.put("reasons",reasons);records.add(item);}catch(Exception failure){throw bad(503,"核对明细格式异常，请保留原报告");}}
        return Map.of("requestId",requestId,"records",records,"hasMore",rows.size()==size,"nextCursor",rows.isEmpty()?after:rows.get(rows.size()-1).get("id"));
    }
    @Transactional(readOnly=true)
    public Map<String,Object> history(AgentActor actor,long before,int size){
        supervisor(actor,false);if(before<0||size<1||size>20)throw bad(400,"核对报告分页无效");
        var rows=jdbc.queryForList("SELECT * FROM detection_identity_reconciliation_report WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT ?",before,before,size);
        return Map.of("records",rows.stream().map(row->receipt(row,false)).toList(),"hasMore",rows.size()==size,"nextCursor",rows.isEmpty()?before:rows.get(rows.size()-1).get("id"));
    }
    private Map<String,Object> receipt(Map<String,Object> row,boolean replayed){
        var result=new LinkedHashMap<String,Object>();
        long tasks=((Number)row.get("task_count")).longValue(),roles=((Number)row.get("role_count")).longValue(),issues=((Number)row.get("issue_count")).longValue();
        if(!PROTOCOL.equals(row.get("protocol"))||tasks<0||roles!=tasks*ROLES.size()||issues<0||issues>roles||!Objects.toString(row.get("dataset_sha256"),"").matches("[a-f0-9]{64}"))throw bad(503,"核对摘要格式异常");
        if(jdbc.queryForObject("SELECT COUNT(*) FROM detection_identity_reconciliation_item WHERE report_id=?",Long.class,row.get("id"))!=issues)throw bad(503,"核对摘要与差异明细数量不一致");
        result.put("id",row.get("id"));result.put("requestId",row.get("request_id"));result.put("protocol",PROTOCOL);result.put("found",true);result.put("state","COMPLETED_SNAPSHOT");result.put("replayed",replayed);
        result.put("actorUserId",row.get("actor_user_id"));result.put("actorName",row.get("actor_name"));result.put("controlRevision",row.get("control_revision"));result.put("identityMode",row.get("identity_mode"));result.put("sourceMode",row.get("source_mode"));
        result.put("startedAt",stamp(row.get("started_at")));result.put("finishedAt",stamp(row.get("finished_at")));result.put("taskCount",tasks);result.put("roleCount",roles);result.put("issueCount",issues);result.put("datasetDigest",row.get("dataset_sha256"));
        try{Map<String,Object> summary=json.readValue(row.get("summary_json").toString(),new TypeReference<Map<String,Object>>(){});if(!PROTOCOL.equals(summary.get("protocol")))throw new IllegalStateException();result.put("summary",summary);}catch(Exception failure){throw bad(503,"核对摘要未能读取");}
        return result;
    }
    private String stamp(Object value){LocalDateTime time=value instanceof java.sql.Timestamp t?t.toLocalDateTime():value instanceof LocalDateTime local?local:null;if(time==null)throw bad(503,"核对时间未知");return time.atOffset(ZONE).toString();}
    private byte[] encoded(Object value){try{return json.writer(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).writeValueAsBytes(value);}catch(Exception error){throw new IllegalStateException("核对摘要编码失败");}}
    private String encode(Object value){return new String(encoded(value),java.nio.charset.StandardCharsets.UTF_8);}
    private MessageDigest digest(){try{return MessageDigest.getInstance("SHA-256");}catch(Exception error){throw new IllegalStateException(error);}}
    private void feed(MessageDigest digest,Object value){byte[] bytes=encoded(value);digest.update(ByteBuffer.allocate(4).putInt(bytes.length).array());digest.update(bytes);}
    private String hash(Object value){var digest=digest();feed(digest,value);return HexFormat.of().formatHex(digest.digest());}
    private static Long number(Object value){return value==null?null:((Number)value).longValue();}
    private static boolean request(String value){return value!=null&&value.matches("[A-Za-z0-9_-]{1,128}");}
    private static ResponseStatusException bad(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
