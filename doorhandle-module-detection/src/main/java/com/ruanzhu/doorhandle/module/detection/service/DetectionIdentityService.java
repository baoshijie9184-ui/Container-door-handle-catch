package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.*;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.util.*;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;

/** Detection owns these columns. Other modules obtain account mappings through contracts. */
@Service @ConditionalOnProperty(prefix="detection.identity",name="enabled",havingValue="true")
public class DetectionIdentityService {
    private static final Map<String,String> ROLES=Map.of("created","created_by","assignee","assignee","reviewer","reviewer","disposition","disposition_operator","rework","rework_operator");
    private final JdbcTemplate jdbc;private final BusinessAccountLookupApi accounts;private final BusinessUserDirectory users;private final OperationsAuditApi audit;private final ObjectMapper json;
    private DetectionIdentityReviewService review;
    @org.springframework.beans.factory.annotation.Autowired public void reviewService(DetectionIdentityReviewService review){this.review=review;}
    private DetectionIdentityEvidenceService evidence;
    @org.springframework.beans.factory.annotation.Autowired(required=false) public void evidenceService(DetectionIdentityEvidenceService evidence){this.evidence=evidence;}
    private DetectionIdentityReconciliationService reconciliation;
    @org.springframework.beans.factory.annotation.Autowired(required=false) public void reconciliationService(DetectionIdentityReconciliationService reconciliation){this.reconciliation=reconciliation;}
    @org.springframework.beans.factory.annotation.Value("${detection.identity.assignment-binding-enabled:false}") private boolean assignmentBinding;
    public boolean assignmentBindingEnabled(){return assignmentBinding;}
    @jakarta.annotation.PostConstruct public void assignmentSchema(){if(assignmentBinding){jdbc.queryForList("SELECT assigned_by_user_id,assigned_by_identity_name,assigned_to_revision,assignment_identity_revision FROM detection_task WHERE 1=0");jdbc.queryForList("SELECT task_id,revision,actor_user_id,assignee_user_id FROM detection_assignment_identity_event WHERE 1=0");}}
    public DetectionIdentityService(JdbcTemplate jdbc,BusinessAccountLookupApi accounts,BusinessUserDirectory users,OperationsAuditApi audit,ObjectMapper json){this.jdbc=jdbc;this.accounts=accounts;this.users=users;this.audit=audit;this.json=json;}
    public boolean active(){String mode=jdbc.queryForObject("SELECT mode FROM detection_identity_control WHERE control_id=1",String.class);if(!Set.of("ACTIVE","PREVIEW").contains(Objects.toString(mode,""))||(evidence!=null&&evidence.active()&&!"ACTIVE".equals(mode)))throw bad(503,"身份授权模式未能核对");return "ACTIVE".equals(mode);}
    public long userId(String username){var id=accounts.findExactUserId(username);if(id==null)throw new SecurityException("账号不存在");return id;}
    public BusinessUserDirectory.Identity current(long userId,String username){return users.current(userId,username);}
    @Deprecated public BusinessUserDirectory.Identity current(String username){var current=users.authenticated();if(!Objects.equals(username,current.username()))throw new SecurityException("缺少原账号稳定身份");return current;}
    public boolean canAccess(String task,long id){return Boolean.TRUE.equals(jdbc.queryForObject("SELECT COUNT(*)>0 FROM detection_task WHERE task_id=? AND "+predicate("","?"),Boolean.class,task,id,id));}
    public String predicate(String alias,String parameter){return "(("+alias+"created_user_id="+parameter+" AND "+bindingPredicate(alias,"created")+(evidence==null?"":" AND "+evidence.authorizationPredicate(alias,"created"))+") OR ("+alias+"assignee_user_id="+parameter+" AND "+bindingPredicate(alias,"assignee")+(evidence==null?"":" AND "+evidence.authorizationPredicate(alias,"assignee"))+"))";}
    private String bindingPredicate(String alias,String role){
        if(alias==null||!alias.matches("(?:[A-Za-z][A-Za-z0-9_]*\\.)?")||!ROLES.containsKey(role))throw new IllegalArgumentException("身份范围无效");
        String name=alias+ROLES.get(role);
        String ordinary="(REGEXP_LIKE(COALESCE("+name+",''),'[^[:space:]]') AND CAST("+alias+role+"_identity_name AS BINARY)=CAST("+name+" AS BINARY))";
        return evidence==null?ordinary:"("+ordinary+" OR "+evidence.missingNamePredicate(alias,role)+")";
    }
    private AgentActor supervisor(AgentActor actor){var current=org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()?users.lockCurrent(actor.userId(),actor.username()):users.current(actor.userId(),actor.username());if(!current.supervisor())throw new SecurityException("仅主管可迁移身份");return new AgentActor(current.userId(),current.username(),AgentActor.Role.SUPERVISOR);}
    private String hash(Object value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writer(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).writeValueAsBytes(value)));}catch(Exception e){throw new IllegalStateException("身份摘要失败");}}
    public record Mapping(String taskId,String role,String expectedName,String snapshot,Long userId,
                          String targetUsername,String targetRole,String targetRevision,String basis){
        public Mapping(String taskId,String role,String expectedName,String snapshot,Long userId){this(taskId,role,expectedName,snapshot,userId,null,null,null,null);}
    }
    public record MissingNameConfirmation(String taskId,String role,String evidenceReference,boolean confirmed){}
    public record Apply(String requestId,List<Mapping> mappings,Long revision,boolean acknowledgedHistory,List<MissingNameConfirmation> missingNames){
        public Apply(String requestId,List<Mapping> mappings,Long revision,boolean acknowledgedHistory){this(requestId,mappings,revision,acknowledgedHistory,null);}
        public Apply(String requestId,List<Mapping> mappings){this(requestId,mappings,null,false,null);}
    }
    public Map<String,Object> preview(AgentActor actor,String after,int size,boolean includeAligned){
        return preview(actor,after,size,includeAligned,"");
    }
    public Map<String,Object> preview(AgentActor actor,String after,int size,boolean includeAligned,String taskFilter){
        if(review!=null&&review.enabled())return review.preview(actor,after,size,includeAligned,taskFilter);
        if(taskFilter==null||!taskFilter.isEmpty()){supervisor(actor);requireReview();}
        var result=new LinkedHashMap<>(preview(actor,after,size));result.put("reviewEnabled",false);return result;
    }
    public Object accounts(AgentActor actor,String keyword){supervisor(actor);requireReview();return review.accounts(actor,keyword);}
    public Object commandStatus(AgentActor actor,String request){supervisor(actor);requireReview();return review.status(actor,request);}
    public Object history(AgentActor actor,long before,int size){supervisor(actor);requireReview();return review.history(actor,before,size);}
    public Object reconcile(AgentActor actor,DetectionIdentityReconciliationService.Create input){supervisor(actor);requireReconciliation();return reconciliation.create(actor,input);}
    public Object reconciliationStatus(AgentActor actor,String request){supervisor(actor);requireReconciliation();return reconciliation.status(actor,request);}
    public Object reconciliationItems(AgentActor actor,String request,long after,int size){supervisor(actor);requireReconciliation();return reconciliation.items(actor,request,after,size);}
    public Object reconciliations(AgentActor actor,long before,int size){supervisor(actor);requireReconciliation();return reconciliation.history(actor,before,size);}
    private void requireReconciliation(){if(reconciliation==null)throw bad(503,"身份快照核对尚未启用，请先核对 V57 和配置");}
    private void requireReview(){if(review==null)throw bad(503,"身份回填确认服务尚未接入");review.requireEnabled();}
    public Map<String,Object> preview(AgentActor actor,String after,int size){
        supervisor(actor);if(size<1||size>200||after==null||after.length()>128)throw bad(400,"分页参数无效");
        var rows=jdbc.queryForList("SELECT task_id,created_by,assignee,reviewer,disposition_operator,rework_operator,created_user_id,assignee_user_id,reviewer_user_id,disposition_user_id,rework_user_id,created_identity_name,assignee_identity_name,reviewer_identity_name,disposition_identity_name,rework_identity_name FROM detection_task WHERE task_id>? ORDER BY task_id LIMIT ?",after,size);
        var result=new ArrayList<Map<String,Object>>();for(var row:rows)for(var entry:new TreeMap<>(ROLES).entrySet()){
            String name=Objects.toString(row.get(entry.getValue()),"");if(name.isBlank())continue;
            String role=entry.getKey();if(row.get(role+"_user_id")!=null&&name.equals(row.get(role+"_identity_name")))continue;
            var item=new LinkedHashMap<String,Object>();item.put("taskId",row.get("task_id"));item.put("role",role);item.put("expectedName",name);item.put("snapshot",hash(new TreeMap<>(row)));item.put("existingUserId",row.get(role+"_user_id"));item.put("existingIdentityName",row.get(role+"_identity_name"));item.put("suggestedUserId",accounts.findExactUserId(name));result.add(item);
        }
        var control=jdbc.queryForMap("SELECT mode,revision FROM detection_identity_control WHERE control_id=1");
        return Map.of("records",result,"nextCursor",rows.isEmpty()?after:rows.get(rows.size()-1).get("task_id"),"hasMore",rows.size()==size,"mode",control.get("mode"),"revision",control.get("revision"));
    }
    public Map<String,Object> apply(AgentActor actor,Apply command){supervisor(actor);requireReview();return review.apply(actor,command);}
    @Transactional public void activate(AgentActor actor,long revision,String request){
        activate(actor,revision,request,false);
    }
    @Transactional public void activate(AgentActor actor,long revision,String request,Boolean sourceProtection){
        var current=supervisor(actor);requireReview();if(request==null||!request.matches("[A-Za-z0-9_-]{1,128}"))throw bad(400,"请求编号无效");
        if(revision<0)throw bad(400,"身份预览版本无效");
        if(sourceProtection==null||sourceProtection!=(evidence!=null))throw bad(409,"身份保护范围已变化，请重新预览并确认");
        var control=jdbc.queryForMap("SELECT * FROM detection_identity_control WHERE control_id=1 FOR UPDATE");
        String digest=hash(Map.of("action","ACTIVATE_IDENTITY_V2","revision",revision,"sourceProtection",sourceProtection));
        var previous=jdbc.queryForList("SELECT actor_user_id,request_sha256 FROM detection_identity_command WHERE request_id=?",request);
        if(!previous.isEmpty()){var old=previous.get(0);if(((Number)old.get("actor_user_id")).longValue()!=current.userId()||!digest.equals(old.get("request_sha256")))throw bad(409,"请求编号冲突");return;}
        if(((Number)control.get("revision")).longValue()!=revision)throw bad(409,"授权模式已变化");
        if(!Set.of("PREVIEW","ACTIVE").contains(Objects.toString(control.get("mode"),"")))throw bad(409,"身份授权模式异常");
        Long unresolved=jdbc.queryForObject("SELECT COUNT(*) FROM detection_task WHERE created_user_id IS NULL OR NOT(COALESCE("+bindingPredicate("","created")+",FALSE)) OR ((COALESCE(assignee,'')<>'' OR assignee_user_id IS NOT NULL OR assignee_identity_name IS NOT NULL) AND (assignee_user_id IS NULL OR NOT(COALESCE("+bindingPredicate("","assignee")+",FALSE))))",Long.class);
        if(unresolved!=0)throw bad(409,"仍有创建人或责任人未完成映射");
        review.lockRequiredAccounts();
        if(evidence!=null)evidence.requireActivationReady();
        boolean changed=!"ACTIVE".equals(control.get("mode"))||(evidence!=null&&!evidence.active());long applied=changed?Math.incrementExact(revision):revision;
        if(changed)jdbc.update("UPDATE detection_identity_control SET mode='ACTIVE',revision=revision+1 WHERE control_id=1");
        if(evidence!=null)evidence.activate(applied);
        audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","DETECTION_IDENTITY","ACTIVATE","all",request,changed?"APPLIED":"NO_CHANGE",applied));
        jdbc.update("INSERT INTO detection_identity_command(request_id,actor_user_id,request_sha256,result_json,created_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP(6))",request,current.userId(),digest,"{\"revision\":"+applied+"}");
    }
    /** Called only immediately after a new insert in the caller's business transaction. */
    @Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY) public void recordCreation(DetectionTask task){
        var current=users.authenticated();
        bindCreation(task,new AgentActor(current.userId(),current.username(),current.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR),assignmentRequest());
    }
    @Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY) public void recordCreation(DetectionTask task,AgentActor actor){bindCreation(task,actor,assignmentRequest());}
    @Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY) public void recordCreation(DetectionTask task,AgentActor actor,String request){bindCreation(task,actor,request);}
    private void bindCreation(DetectionTask task,AgentActor actor,String request){
        var current=users.current(actor.userId(),actor.username());
        var row=locked(task);
        if(!Objects.equals(current.username(),row.get("created_by"))||!Objects.equals(task.getCreatedBy(),row.get("created_by")))throw bad(409,"创建人身份与任务快照不一致");
        var previous=(Number)row.get("created_user_id");
        if(previous!=null && (previous.longValue()!=current.userId()||!Objects.equals(row.get("created_identity_name"),current.username())))throw bad(409,"任务已有另一创建人关联");
        jdbc.update("UPDATE detection_task SET created_user_id=?,created_identity_name=? WHERE task_id=?",current.userId(),current.username(),task.getTaskId());
        if(evidence!=null)evidence.record(task.getTaskId(),"created",actor,"NEW_CREATION",request,null);
    }
    /** A deliberate new assignment is different from inferring an old assignment from its display name. */
    @Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY) public void recordAssignment(DetectionTask task,AgentUserDirectory.Inspector recipient){
        var actor=users.authenticated();if(!actor.supervisor())throw new SecurityException("分派需要当前主管权限");
        var row=locked(task);String name=Objects.toString(row.get("assignee"),"");
        if(name.isBlank()||!Objects.equals(name,task.getAssignee()))throw bad(409,"责任人快照已变化");
        if(recipient==null||!name.equals(recipient.username()))throw bad(409,"缺少固定的责任人账号");
        var assignee=users.current(recipient.userId(),name);if(assignee.supervisor())throw bad(400,"责任人必须是员工账号");
        String request=assignmentBinding||evidence!=null?assignmentRequest():null;
        jdbc.update("UPDATE detection_task SET assignee_user_id=?,assignee_identity_name=? WHERE task_id=?",recipient.userId(),name,task.getTaskId());
        if(assignmentBinding){
            long revision=Math.incrementExact(((Number)row.get("assignment_identity_revision")).longValue());
            jdbc.update("UPDATE detection_task SET assigned_by_user_id=?,assigned_by_identity_name=?,assigned_to_revision=?,assignment_identity_revision=? WHERE task_id=?",actor.userId(),actor.username(),recipient.revision(),revision,task.getTaskId());
            jdbc.update("INSERT INTO detection_assignment_identity_event(task_id,revision,actor_user_id,actor_name,assignee_user_id,assignee_name,assignee_revision,request_id) VALUES(?,?,?,?,?,?,?,?)",task.getTaskId(),revision,actor.userId(),actor.username(),recipient.userId(),name,recipient.revision(),request);
            audit.append(new OperationsAuditApi.Event(new AgentActor(actor.userId(),actor.username(),AgentActor.Role.SUPERVISOR),"ENTERPRISE","DETECTION_IDENTITY","ASSIGN_IDENTITY",task.getTaskId(),request,"APPLIED",revision));
        }
        if(evidence!=null)evidence.record(task.getTaskId(),"assignee",new AgentActor(actor.userId(),actor.username(),AgentActor.Role.SUPERVISOR),"QUALITY_ASSIGNMENT",request,null);
    }
    public record AssignmentIdentity(Long assignedByUserId,String assignedByName,Long assigneeUserId,String assigneeRevision,Long revision){}
    public AssignmentIdentity assignmentIdentity(String task){
        if(!assignmentBinding)return null;
        var row=jdbc.queryForMap("SELECT assigned_by_user_id,assigned_by_identity_name,assigned_to_revision,assignment_identity_revision,assignee_user_id,assignee_identity_name,assignee FROM detection_task WHERE task_id=?",task);
        boolean aligned=Objects.equals(row.get("assignee_identity_name"),row.get("assignee"));
        return new AssignmentIdentity(aligned?number(row.get("assigned_by_user_id")):null,aligned?(String)row.get("assigned_by_identity_name"):null,aligned?number(row.get("assignee_user_id")):null,aligned?(String)row.get("assigned_to_revision"):null,number(row.get("assignment_identity_revision")));
    }
    private static Long number(Object value){return value==null?null:((Number)value).longValue();}
    private String assignmentRequest(){
        String value=null;
        var attributes=org.springframework.web.context.request.RequestContextHolder.getRequestAttributes();
        if(attributes instanceof org.springframework.web.context.request.ServletRequestAttributes http){value=http.getRequest().getHeader("X-Request-ID");if(value==null&&http.getResponse()!=null)value=http.getResponse().getHeader("X-Request-ID");}
        if(value==null)value=UUID.randomUUID().toString();
        if(!value.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("分派请求编号无效");return value;
    }
    @Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY) public void recordPerformed(DetectionTask task,String role){
        if(!Set.of("reviewer","disposition","rework").contains(role))throw new IllegalArgumentException("操作人角色无效");
        var actor=users.authenticated();var row=locked(task);String name=Objects.toString(row.get(ROLES.get(role)),"");
        if(!Objects.equals(actor.username(),name))throw bad(409,"操作人快照与当前账号不一致");
        jdbc.update("UPDATE detection_task SET "+role+"_user_id=?,"+role+"_identity_name=? WHERE task_id=?",actor.userId(),name,task.getTaskId());
        if(evidence!=null)evidence.record(task.getTaskId(),role,new AgentActor(actor.userId(),actor.username(),actor.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR),"PERFORMED_OPERATION",assignmentRequest(),null);
    }
    private Map<String,Object> locked(DetectionTask task){
        if(task==null||task.getTaskId()==null)throw new IllegalArgumentException("任务编号无效");
        return jdbc.queryForMap("SELECT * FROM detection_task WHERE task_id=? FOR UPDATE",task.getTaskId());
    }
    /** No lazy name-based backfill. Unknown historical identities stay pending for supervisor mapping. */
    @Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY) public void sync(DetectionTask task){
        var row=locked(task);
        for(var entry:ROLES.entrySet()){
            String role=entry.getKey(),name=Objects.toString(row.get(entry.getValue()),"");
            if(!role.equals("created") && name.isBlank() && (row.get(role+"_user_id")!=null||row.get(role+"_identity_name")!=null) && (evidence==null||!evidence.confirmedMissingName(task.getTaskId(),role)))
                jdbc.update("UPDATE detection_task SET "+role+"_user_id=NULL,"+role+"_identity_name=NULL WHERE task_id=?",task.getTaskId());
        }
        if(evidence!=null)evidence.invalidateVacant(task.getTaskId());
    }
    /** Explicit business reset revokes even a certificate for an already-empty historical field. */
    @Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY)
    public void clearPerformed(DetectionTask task,String... roles){
        var row=locked(task);
        for(String role:new TreeSet<>(Arrays.asList(roles))){
            if(!Set.of("reviewer","disposition","rework").contains(role)||!Objects.toString(row.get(ROLES.get(role)),"").isBlank())throw bad(409,"仅能撤销业务已明确清空的操作人关联");
            jdbc.update("UPDATE detection_task SET "+role+"_user_id=NULL,"+role+"_identity_name=NULL WHERE task_id=?",task.getTaskId());
        }
        if(evidence!=null)evidence.invalidateVacant(task.getTaskId());
    }
    private static ResponseStatusException bad(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
