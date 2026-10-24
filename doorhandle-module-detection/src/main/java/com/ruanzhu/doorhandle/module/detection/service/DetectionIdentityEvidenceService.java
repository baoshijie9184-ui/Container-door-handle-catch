package com.ruanzhu.doorhandle.module.detection.service;

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
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import java.security.MessageDigest;
import java.util.*;

/** Detection-owned metadata journal. A matching name or an old ID never creates evidence. */
@Service
@ConditionalOnProperty(prefix="detection.identity",name="evidence-enabled",havingValue="true")
public class DetectionIdentityEvidenceService {
    private static final Map<String,String> ROLES=Map.of("created","created_by","assignee","assignee",
            "reviewer","reviewer","disposition","disposition_operator","rework","rework_operator");
    private static final String ZERO="0".repeat(64);
    private final JdbcTemplate jdbc;private final BusinessAccountLookupApi accounts;
    private final BusinessUserDirectory users;private final OperationsAuditApi audit;private final ObjectMapper json;
    @Value("${detection.identity.enabled:false}") private boolean identityEnabled;
    @Value("${detection.identity.review-enabled:false}") private boolean reviewEnabled;
    @Value("${detection.identity.missing-name-review-enabled:false}") private boolean missingNameReview;
    public DetectionIdentityEvidenceService(JdbcTemplate jdbc,BusinessAccountLookupApi accounts,BusinessUserDirectory users,
            OperationsAuditApi audit,ObjectMapper json){this.jdbc=jdbc;this.accounts=accounts;this.users=users;this.audit=audit;this.json=json;}
    @jakarta.annotation.PostConstruct public void schema(){
        if(!identityEnabled||!reviewEnabled)throw new IllegalStateException("身份来源记录需要稳定身份与回填确认服务");
        jdbc.queryForList("SELECT task_id,identity_role,event_id,revision,event_sha256 FROM detection_identity_binding WHERE 1=0");
        jdbc.queryForList("SELECT id,task_id,identity_role,revision,bound_user_id,bound_identity_name,target_revision,actor_user_id,actor_name,source_kind,request_id,source_batch_id,previous_sha256,event_sha256 FROM detection_identity_binding_event WHERE 1=0");
        if(missingNameReview)jdbc.queryForList("SELECT batch_id,task_id,identity_role,original_name,source_snapshot,target_user_id,evidence_reference FROM detection_identity_missing_name_evidence WHERE 1=0");
        if(!missingNameReview&&Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)>0 FROM detection_identity_binding_event WHERE source_kind='SUPERVISOR_MISSING_NAME'",Boolean.class)))throw new IllegalStateException("缺失名称确认历史必须保留兼容读取与保护开关");
        active();
    }
    public boolean missingNameReviewEnabled(){return missingNameReview;}
    public boolean active(){String mode=jdbc.queryForObject("SELECT mode FROM detection_identity_source_control WHERE control_id=1",String.class);if(!Set.of("COLLECTING","ACTIVE").contains(Objects.toString(mode,"")))throw bad(503,"身份来源模式未能核对");return "ACTIVE".equals(mode);}
    public String authorizationPredicate(String alias,String role){return "EXISTS(SELECT 1 FROM detection_identity_source_control identity_source_mode WHERE identity_source_mode.control_id=1 AND (identity_source_mode.mode='COLLECTING' OR (identity_source_mode.mode='ACTIVE' AND "+predicate(alias,role)+")))";}
    public String predicate(String alias,String role){
        if(alias==null||!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?")||!ROLES.containsKey(Objects.toString(role,"")))throw new IllegalArgumentException("身份来源范围无效");
        String task=alias.isEmpty()?"detection_task.":alias;
        String ordinary="EXISTS(SELECT 1 FROM detection_identity_binding identity_head JOIN detection_identity_binding_event identity_event ON identity_event.id=identity_head.event_id AND identity_event.task_id=identity_head.task_id AND identity_event.identity_role=identity_head.identity_role AND identity_event.revision=identity_head.revision AND identity_event.event_sha256=identity_head.event_sha256 WHERE identity_head.task_id="+task+"task_id AND identity_head.identity_role='"+role+"' AND identity_event.source_kind IN ('NEW_CREATION','QUALITY_ASSIGNMENT','PERFORMED_OPERATION','SUPERVISOR_MAPPING') AND identity_event.bound_user_id="+task+role+"_user_id AND CAST(identity_event.bound_identity_name AS BINARY)=CAST("+task+ROLES.get(role)+" AS BINARY))";
        return "("+ordinary+" OR "+missingNamePredicate(alias,role)+")";
    }
    /** A missing display name is never a name match. Only its current explicit certificate can bind it. */
    public String missingNamePredicate(String alias,String role){
        if(alias==null||!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?")||!ROLES.containsKey(Objects.toString(role,"")))throw new IllegalArgumentException("身份来源范围无效");
        if(!missingNameReview)return "FALSE";
        String task=alias.isEmpty()?"detection_task.":alias,name=task+ROLES.get(role);
        return "EXISTS(SELECT 1 FROM detection_identity_binding missing_head JOIN detection_identity_binding_event missing_event ON missing_event.id=missing_head.event_id AND missing_event.task_id=missing_head.task_id AND missing_event.identity_role=missing_head.identity_role AND missing_event.revision=missing_head.revision AND missing_event.event_sha256=missing_head.event_sha256 JOIN detection_identity_mapping_batch missing_batch ON missing_batch.id=missing_event.source_batch_id AND missing_batch.request_id=missing_event.request_id AND missing_batch.actor_user_id=missing_event.actor_user_id JOIN detection_identity_mapping_item missing_item ON missing_item.batch_id=missing_batch.id AND missing_item.task_id=missing_head.task_id AND missing_item.identity_role=missing_head.identity_role JOIN detection_identity_missing_name_evidence missing_proof ON missing_proof.batch_id=missing_item.batch_id AND missing_proof.task_id=missing_item.task_id AND missing_proof.identity_role=missing_item.identity_role AND missing_proof.source_snapshot=missing_item.source_snapshot WHERE missing_head.task_id="+task+"task_id AND missing_head.identity_role='"+role+"' AND missing_event.source_kind='SUPERVISOR_MISSING_NAME' AND missing_event.bound_user_id="+task+role+"_user_id AND missing_item.target_user_id=missing_event.bound_user_id AND missing_proof.target_user_id=missing_event.bound_user_id AND missing_proof.evidence_reference<>'' AND (CAST(missing_proof.original_name AS BINARY)<=>CAST("+name+" AS BINARY)) AND CAST(missing_item.source_name AS BINARY)=CAST(COALESCE("+name+",'') AS BINARY) AND CAST(missing_event.bound_identity_name AS BINARY)=CAST(missing_item.source_name AS BINARY) AND CAST("+task+role+"_identity_name AS BINARY)=CAST(missing_item.source_name AS BINARY))";
    }
    public boolean confirmedMissingName(String task,String role){return missingNameReview&&Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)=1 FROM detection_task WHERE task_id=? AND "+missingNamePredicate("",role),Boolean.class,task));}
    /** Caller has performed the actual operation and stored stable IDs in this same transaction. */
    @Transactional(propagation=Propagation.MANDATORY)
    public void record(String task,String role,AgentActor actor,String kind,String request,Long batch){
        if(!ROLES.containsKey(Objects.toString(role,""))||!Set.of("NEW_CREATION","QUALITY_ASSIGNMENT","PERFORMED_OPERATION","SUPERVISOR_MAPPING","SUPERVISOR_MISSING_NAME").contains(Objects.toString(kind,""))
                ||request==null||!request.matches("[A-Za-z0-9_-]{1,128}"))throw bad(400,"身份来源参数无效");
        var current=users.lockCurrent(actor.userId(),actor.username());
        var row=jdbc.queryForMap("SELECT * FROM detection_task WHERE task_id=? FOR UPDATE",task);
        Long subject=number(row.get(role+"_user_id"));String name=Objects.toString(row.get(ROLES.get(role)),"");
        boolean missing=kind.equals("SUPERVISOR_MISSING_NAME");
        if(subject==null||(name.isBlank()&&!(missing&&missingNameReview))||(!name.isBlank()&&missing)||!Objects.equals(name,row.get(role+"_identity_name")))throw bad(409,"身份来源与实际任务不一致");
        if(kind.equals("NEW_CREATION")&&(!role.equals("created")||subject!=current.userId()))throw new SecurityException("创建人来源必须是实际创建账号");
        if(kind.equals("QUALITY_ASSIGNMENT")&&(!role.equals("assignee")||!current.supervisor()))throw new SecurityException("分派来源需要当前主管");
        if(kind.equals("PERFORMED_OPERATION")&&(!Set.of("reviewer","disposition","rework").contains(role)||subject!=current.userId()))throw new SecurityException("操作人来源必须是实际执行账号");
        if(kind.equals("SUPERVISOR_MAPPING")||missing){
            if(!current.supervisor()||batch==null||!Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)=1 FROM detection_identity_mapping_batch b JOIN detection_identity_mapping_item i ON i.batch_id=b.id WHERE b.id=? AND b.request_id=? AND b.actor_user_id=? AND i.task_id=? AND i.identity_role=? AND i.target_user_id=? AND CAST(i.source_name AS BINARY)=CAST(? AS BINARY)",Boolean.class,batch,request,current.userId(),task,role,subject,name)))throw bad(409,"缺少对应的主管回填依据");
            if(missing&&!Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)=1 FROM detection_identity_missing_name_evidence p JOIN detection_identity_mapping_item i ON i.batch_id=p.batch_id AND i.task_id=p.task_id AND i.identity_role=p.identity_role AND i.source_snapshot=p.source_snapshot WHERE p.batch_id=? AND p.task_id=? AND p.identity_role=? AND p.target_user_id=? AND (CAST(p.original_name AS BINARY)<=>CAST(? AS BINARY)) AND p.evidence_reference<>''",Boolean.class,batch,task,role,subject,row.get(ROLES.get(role)))))throw bad(409,"缺失名称确认依据未保存");
        }else if(batch!=null)throw bad(400,"业务操作不能冒用历史回填批次");
        var target=accounts.describe(subject);if(target==null)throw bad(409,"身份来源的目标账号已失效");accounts.lock(target);
        if(!kind.equals("SUPERVISOR_MAPPING")&&!missing&&!name.equals(target.username()))throw bad(409,"业务操作的目标账号名称已变化");
        var freshActor=new AgentActor(current.userId(),current.username(),current.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);
        var event=append(task,role,subject,name,target.revision(),freshActor,kind,request,batch);
        audit.append(new OperationsAuditApi.Event(freshActor,"ENTERPRISE","DETECTION_IDENTITY_SOURCE","BIND_"+role.toUpperCase(Locale.ROOT),task,request,"APPLIED",event));
    }
    private long append(String task,String role,Long subject,String name,String targetRevision,AgentActor actor,String kind,String request,Long batch){
        var heads=jdbc.queryForList("SELECT event_id,revision,event_sha256 FROM detection_identity_binding WHERE task_id=? AND identity_role=? FOR UPDATE",task,role);
        var head=heads.isEmpty()?null:heads.get(0);
        if(head!=null&&(((Number)head.get("revision")).longValue()<1||!Objects.toString(head.get("event_sha256"),"").matches("[a-f0-9]{64}")
                ||!Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)=1 FROM detection_identity_binding_event WHERE id=? AND task_id=? AND identity_role=? AND revision=? AND event_sha256=?",Boolean.class,head.get("event_id"),task,role,head.get("revision"),head.get("event_sha256")))))throw bad(503,"原身份来源不完整，停止写入并保留核对");
        var old=jdbc.queryForList("SELECT id,revision,bound_user_id,bound_identity_name,target_revision,actor_user_id,actor_name,source_kind,source_batch_id,event_sha256 FROM detection_identity_binding_event WHERE task_id=? AND identity_role=? AND request_id=?",task,role,request);
        if(!old.isEmpty()){
            var event=old.get(0);
            if(head==null||!Objects.equals(number(event.get("id")),number(head.get("event_id")))||!Objects.equals(subject,number(event.get("bound_user_id")))
                    ||!Objects.equals(number(event.get("revision")),number(head.get("revision")))||!Objects.equals(event.get("event_sha256"),head.get("event_sha256"))
                    ||!Objects.equals(actor==null?null:actor.userId(),number(event.get("actor_user_id")))||!Objects.equals(actor==null?null:actor.username(),event.get("actor_name"))
                    ||!Objects.equals(name,event.get("bound_identity_name"))||!Objects.equals(targetRevision,event.get("target_revision"))||!kind.equals(event.get("source_kind"))||!Objects.equals(batch,number(event.get("source_batch_id"))))throw bad(409,"身份来源请求已用于其他状态，请先核对原业务回执");
            return ((Number)event.get("revision")).longValue();
        }
        long revision=head==null?1:Math.incrementExact(((Number)head.get("revision")).longValue());
        String previous=head==null?ZERO:(String)head.get("event_sha256");
        var payload=new TreeMap<String,Object>();payload.put("task",task);payload.put("role",role);payload.put("revision",revision);
        payload.put("userId",subject);payload.put("identityName",name);payload.put("targetRevision",targetRevision);payload.put("actorId",actor==null?null:actor.userId());
        payload.put("actorName",actor==null?null:actor.username());payload.put("kind",kind);payload.put("requestId",request);payload.put("batchId",batch);payload.put("previous",previous);
        String digest=hash(payload);
        jdbc.update("INSERT INTO detection_identity_binding_event(task_id,identity_role,revision,bound_user_id,bound_identity_name,target_revision,actor_user_id,actor_name,source_kind,request_id,source_batch_id,previous_sha256,event_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",task,role,revision,subject,name,targetRevision,actor==null?null:actor.userId(),actor==null?null:actor.username(),kind,request,batch,previous,digest);
        long event=jdbc.queryForObject("SELECT id FROM detection_identity_binding_event WHERE task_id=? AND identity_role=? AND revision=?",Long.class,task,role,revision);
        if(head==null)jdbc.update("INSERT INTO detection_identity_binding(task_id,identity_role,event_id,revision,event_sha256) VALUES(?,?,?,?,?)",task,role,event,revision,digest);
        else if(jdbc.update("UPDATE detection_identity_binding SET event_id=?,revision=?,event_sha256=? WHERE task_id=? AND identity_role=? AND revision=?",event,revision,digest,task,role,revision-1)!=1)throw bad(409,"身份来源版本已变化");
        return revision;
    }
    /** Empty business fields revoke the current source without inventing a human operator. */
    @Transactional(propagation=Propagation.MANDATORY)
    public void invalidateVacant(String task){
        var row=jdbc.queryForMap("SELECT * FROM detection_task WHERE task_id=? FOR UPDATE",task);
        for(var entry:ROLES.entrySet())if(!entry.getKey().equals("created")&&Objects.toString(row.get(entry.getValue()),"").isBlank()&&!confirmedMissingName(task,entry.getKey())){
            var current=jdbc.queryForList("SELECT e.source_kind FROM detection_identity_binding h JOIN detection_identity_binding_event e ON e.id=h.event_id WHERE h.task_id=? AND h.identity_role=?",task,entry.getKey());
            if(!current.isEmpty()&&!"OBSERVED_CLEAR".equals(current.get(0).get("source_kind")))append(task,entry.getKey(),null,null,null,null,"OBSERVED_CLEAR","observed-clear-"+UUID.randomUUID(),null);
        }
    }
    public Map<String,Map<String,Map<String,Object>>> sources(Collection<String> tasks){
        if(tasks==null||tasks.size()>100)throw bad(400,"身份来源分页无效");
        if(tasks.isEmpty())return Map.of();
        var ids=new TreeSet<>(tasks);if(ids.stream().anyMatch(id->id.isBlank()||id.length()>128))throw bad(400,"身份来源任务无效");
        var rows=jdbc.queryForList("SELECT e.task_id,e.identity_role,e.source_kind,e.revision,e.bound_user_id,e.bound_identity_name,e.actor_user_id,e.actor_name,e.request_id,e.source_batch_id,e.event_sha256,h.event_sha256 AS head_sha256,e.revision=h.revision AS revision_matches FROM detection_identity_binding h JOIN detection_identity_binding_event e ON e.id=h.event_id AND e.task_id=h.task_id AND e.identity_role=h.identity_role WHERE h.task_id IN ("+String.join(",",Collections.nCopies(ids.size(),"?"))+")",ids.toArray());
        var result=new HashMap<String,Map<String,Map<String,Object>>>();
        for(var row:rows){
            var item=new LinkedHashMap<String,Object>();
            boolean sound=Objects.equals(row.get("event_sha256"),row.get("head_sha256"))&&Boolean.TRUE.equals(jdbcBoolean(row.get("revision_matches")))
                    &&Objects.toString(row.get("event_sha256"),"").matches("[a-f0-9]{64}")&&number(row.get("revision"))!=null&&number(row.get("revision"))>0
                    &&Set.of("NEW_CREATION","QUALITY_ASSIGNMENT","PERFORMED_OPERATION","SUPERVISOR_MAPPING","SUPERVISOR_MISSING_NAME").contains(Objects.toString(row.get("source_kind"),""));
            boolean missingConfirmed="SUPERVISOR_MISSING_NAME".equals(row.get("source_kind"))&&confirmedMissingName(row.get("task_id").toString(),row.get("identity_role").toString());
            if("SUPERVISOR_MISSING_NAME".equals(row.get("source_kind"))&&!missingConfirmed)sound=false;
            item.put("state",sound?"SOURCE_RECORDED":"SOURCE_INVALID");
            item.put("missing_name_confirmed",missingConfirmed&&sound);
            for(String key:List.of("source_kind","revision","bound_user_id","bound_identity_name","actor_user_id","actor_name","request_id","source_batch_id","event_sha256"))item.put(key,row.get(key));
            result.computeIfAbsent(row.get("task_id").toString(),unused->new HashMap<>()).put(row.get("identity_role").toString(),item);
        }
        return result;
    }
    public boolean matches(String task,String role){return Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)=1 FROM detection_task WHERE task_id=? AND "+predicate("",role),Boolean.class,task));}
    @Transactional(propagation=Propagation.MANDATORY)
    public void requireActivationReady(){
        Long count=jdbc.queryForObject("SELECT COUNT(*) FROM detection_task WHERE NOT("+predicate("","created")+") OR ((COALESCE(assignee,'')<>'' OR assignee_user_id IS NOT NULL OR assignee_identity_name IS NOT NULL) AND NOT("+predicate("","assignee")+"))",Long.class);
        if(count==null||count!=0)throw bad(409,"仍有创建人或责任人的身份来源待核对，请明确回填后再启用");
    }
    @Transactional(propagation=Propagation.MANDATORY)
    public void activate(long revision){
        var row=jdbc.queryForMap("SELECT mode FROM detection_identity_source_control WHERE control_id=1 FOR UPDATE");
        if("ACTIVE".equals(row.get("mode")))return;
        if(!"COLLECTING".equals(row.get("mode")))throw bad(503,"身份来源模式异常");
        requireActivationReady();
        if(jdbc.update("UPDATE detection_identity_source_control SET mode='ACTIVE',activation_revision=? WHERE control_id=1 AND mode='COLLECTING'",revision)!=1)throw bad(409,"身份来源模式已变化");
    }
    private String hash(Object value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writer(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).writeValueAsBytes(value)));}catch(Exception error){throw new IllegalStateException("身份来源摘要保存失败");}}
    private static Long number(Object value){return value==null?null:((Number)value).longValue();}
    private static Boolean jdbcBoolean(Object value){return value instanceof Boolean b?b:value instanceof Number n?n.intValue()!=0:false;}
    private static ResponseStatusException bad(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
