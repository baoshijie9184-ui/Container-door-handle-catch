package com.ruanzhu.doorhandle.module.detection.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.OperationsAuditApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi.Account;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import java.security.MessageDigest;
import java.util.*;

/** Supervisor review of historical identities. Does not infer ownership from a current name. */
@Service
@ConditionalOnProperty(prefix="detection.identity", name="enabled", havingValue="true")
public class DetectionIdentityReviewService {
    private static final Map<String,String> ROLES=Map.of("created","created_by","assignee","assignee",
            "reviewer","reviewer","disposition","disposition_operator","rework","rework_operator");
    private static final String FIELDS="task_id,updated_at,status,flow_status,review_status,created_by,assignee,reviewer,disposition_operator,rework_operator,"
            +"created_user_id,assignee_user_id,reviewer_user_id,disposition_user_id,rework_user_id,"
            +"created_identity_name,assignee_identity_name,reviewer_identity_name,disposition_identity_name,rework_identity_name";
    private static final Set<String> BASES=Set.of("SOURCE_RECORD_CHECKED","ORGANIZATION_RECORD_CHECKED",
            "ACCOUNT_RENAME_VERIFIED","MANUAL_RECONCILIATION");
    private final JdbcTemplate jdbc;
    private final BusinessAccountLookupApi accounts;
    private final BusinessUserDirectory users;
    private final OperationsAuditApi audit;
    private final ObjectMapper json;
    @Value("${detection.identity.review-enabled:false}") private boolean enabled;
    @Value("${detection.identity.missing-name-review-enabled:false}") private boolean missingNameReview;
    private DetectionIdentityEvidenceService evidence;
    @org.springframework.beans.factory.annotation.Autowired(required=false) public void evidenceService(DetectionIdentityEvidenceService evidence){this.evidence=evidence;}
    private boolean reconciliationEnabled;
    @org.springframework.beans.factory.annotation.Autowired(required=false) public void reconciliationService(DetectionIdentityReconciliationService value){this.reconciliationEnabled=true;}

    public DetectionIdentityReviewService(JdbcTemplate jdbc,BusinessAccountLookupApi accounts,
            BusinessUserDirectory users,OperationsAuditApi audit,ObjectMapper json){
        this.jdbc=jdbc;this.accounts=accounts;this.users=users;this.audit=audit;this.json=json;
    }
    public boolean enabled(){return enabled;}
    public void requireEnabled(){if(!enabled)throw bad(503,"身份回填写入尚未启用，请先完成 V55 及兼容基线核对");}
    @jakarta.annotation.PostConstruct public void schema(){
        if(missingNameReview&&(!enabled||evidence==null||!evidence.missingNameReviewEnabled()))throw new IllegalStateException("缺失名称确认需要身份回填与兼容来源保护服务");
        if(enabled){
            jdbc.queryForList("SELECT request_id,actor_user_id,command_sha256,revision_before,revision_after,applied_count,result_json FROM detection_identity_mapping_batch WHERE 1=0");
            jdbc.queryForList("SELECT batch_id,task_id,identity_role,source_snapshot,target_user_id,target_revision,confirmation_basis FROM detection_identity_mapping_item WHERE 1=0");
            if(missingNameReview)jdbc.queryForList("SELECT batch_id,task_id,identity_role,original_name,source_snapshot,target_user_id,evidence_reference FROM detection_identity_missing_name_evidence WHERE 1=0");
        }
    }
    private AgentActor supervisor(AgentActor actor,boolean lock){
        var current=lock?users.lockCurrent(actor.userId(),actor.username()):users.current(actor.userId(),actor.username());
        if(!current.supervisor())throw new SecurityException("仅主管可核对历史身份");
        return new AgentActor(current.userId(),current.username(),AgentActor.Role.SUPERVISOR);
    }
    public List<Account> accounts(AgentActor actor,String keyword){
        supervisor(actor,false);requireEnabled();return accounts.search(keyword,20);
    }
    @Transactional(readOnly=true)
    public Map<String,Object> preview(AgentActor actor,String after,int size,boolean includeAligned){
        return preview(actor,after,size,includeAligned,"");
    }
    @Transactional(readOnly=true)
    public Map<String,Object> preview(AgentActor actor,String after,int size,boolean includeAligned,String taskFilter){
        supervisor(actor,false);requireEnabled();
        if(size<1||size>100||after==null||after.length()>128||taskFilter==null||taskFilter.length()>128)throw bad(400,"分页或任务定位参数无效");
        var rows=taskFilter.isEmpty()?jdbc.queryForList("SELECT "+FIELDS+" FROM detection_task WHERE task_id>? ORDER BY task_id LIMIT ?",after,size):jdbc.queryForList("SELECT "+FIELDS+" FROM detection_task WHERE task_id=?",taskFilter);
        var sources=evidence==null?Map.<String,Map<String,Map<String,Object>>>of():evidence.sources(rows.stream().map(row->row.get("task_id").toString()).toList());
        var result=new ArrayList<Map<String,Object>>();
        var cached=new HashMap<Long,Account>();var missing=new HashSet<Long>();
        var candidateIds=new HashMap<String,Long>();
        for(var row:rows)for(var entry:new TreeMap<>(ROLES).entrySet()){
            String name=Objects.toString(row.get(entry.getValue()),"");
            String role=entry.getKey();Long oldId=number(row.get(role+"_user_id"));
            boolean aligned=oldId!=null&&name.equals(row.get(role+"_identity_name"));
            Account original=account(oldId,cached,missing);
            var source=sources.getOrDefault(row.get("task_id").toString(),Map.of()).getOrDefault(role,Map.of("state","SOURCE_UNVERIFIED"));
            if(name.isBlank()&&!role.equals("created")&&oldId==null&&row.get(role+"_identity_name")==null&&(!source.containsKey("source_kind")||"OBSERVED_CLEAR".equals(source.get("source_kind"))))continue;
            boolean sourceMatches="SOURCE_RECORDED".equals(source.get("state"))&&Objects.equals(oldId,number(source.get("bound_user_id")))&&name.equals(source.get("bound_identity_name"));
            boolean confirmedMissing=name.isBlank()&&sourceMatches&&Boolean.TRUE.equals(source.get("missing_name_confirmed"));
            if((!name.isBlank()||confirmedMissing)&&aligned&&original!=null&&(evidence==null||sourceMatches)&&!includeAligned)continue;
            if(!name.isBlank()&&!candidateIds.containsKey(name))candidateIds.put(name,accounts.findExactUserId(name));
            Long candidateId=candidateIds.get(name);Account candidate=account(candidateId,cached,missing);
            var item=new LinkedHashMap<String,Object>();
            item.put("taskId",row.get("task_id"));item.put("role",role);item.put("expectedName",name);
            item.put("taskStatus",row.get("status"));item.put("flowStatus",row.get("flow_status"));item.put("reviewStatus",row.get("review_status"));item.put("taskUpdatedAt",row.get("updated_at")==null?null:stamp(row.get("updated_at")));
            item.put("snapshot",hash(new TreeMap<>(row)));item.put("existingUserId",oldId);
            item.put("missingName",name.isBlank());item.put("mappingAllowed",!name.isBlank()||missingNameReview);item.put("mappingBlockedReason",name.isBlank()?missingNameReview?"请核实原始资料、填写资料编号并逐条确认；服务器不推断缺失名称的归属":"历史名称缺失，需启用受控缺失名称确认后核实资料，不推断归属":"");
            item.put("existingIdentityName",row.get(role+"_identity_name"));item.put("existingAccount",original);
            item.put("suggestedUserId",candidate==null?null:candidate.userId());item.put("candidateAccount",candidate);
            var sourceView=new LinkedHashMap<>(source);if("SOURCE_RECORDED".equals(source.get("state"))&&!sourceMatches)sourceView.put("state","SOURCE_MISMATCH");item.put("source",sourceView);
            item.put("state",oldId!=null&&original==null?"ORIGINAL_ACCOUNT_UNAVAILABLE":name.isBlank()?confirmedMissing?"MISSING_NAME_CONFIRMED":"MISSING_NAME":aligned&&evidence!=null&&!sourceMatches?"SOURCE_UNVERIFIED":aligned?"ALREADY_ALIGNED":
                    candidate==null?"UNMATCHED":oldId!=null&&!Objects.equals(oldId,candidate.userId())?"DIFFERENT_CURRENT_ACCOUNT":"CANDIDATE_ONLY");
            result.add(item);
        }
        var control=jdbc.queryForMap("SELECT mode,revision FROM detection_identity_control WHERE control_id=1");
        var response=new LinkedHashMap<String,Object>(Map.of("records",result,"nextCursor",rows.isEmpty()?after:rows.get(rows.size()-1).get("task_id"),
                "hasMore",taskFilter.isEmpty()&&rows.size()==size,"mode",control.get("mode"),"revision",control.get("revision"),
                "reviewEnabled",true,"protocol","identity-map-v2","sourceEvidenceEnabled",evidence!=null,"sourceMode",evidence==null?"DISABLED":evidence.active()?"ACTIVE":"COLLECTING","reconciliationEnabled",reconciliationEnabled));
        response.put("missingNameReviewEnabled",missingNameReview);return response;
    }
    private Account account(Long id,Map<Long,Account> cached,Set<Long> missing){
        if(id==null||missing.contains(id))return null;
        if(!cached.containsKey(id)){var value=accounts.describe(id);if(value==null)missing.add(id);else cached.put(id,value);}
        return cached.get(id);
    }
    @Transactional
    public Map<String,Object> apply(AgentActor actor,DetectionIdentityService.Apply command){
        requireEnabled();var current=supervisor(actor,true);
        if(command==null||!request(command.requestId())||command.revision()==null||command.revision()<0
                ||!command.acknowledgedHistory()||command.mappings()==null||command.mappings().isEmpty()||command.mappings().size()>200)
            throw bad(400,"需要确认历史归属、预览版本和完整目标账号快照");
        var mappings=new ArrayList<>(command.mappings());var unique=new HashSet<List<String>>();
        for(var mapping:mappings){
            if(mapping==null||mapping.taskId()==null||mapping.taskId().isBlank()||mapping.taskId().length()>128
                    ||mapping.role()==null||!ROLES.containsKey(mapping.role())||mapping.expectedName()==null||mapping.expectedName().length()>64
                    ||mapping.snapshot()==null||!mapping.snapshot().matches("[a-f0-9]{64}")||mapping.userId()==null||mapping.userId()<1
                    ||mapping.targetUsername()==null||mapping.targetUsername().isBlank()||mapping.targetUsername().length()>64
                    ||!Set.of("ADMIN","SUPERVISOR","INSPECTOR","OPERATOR").contains(Objects.toString(mapping.targetRole(),""))
                    ||mapping.targetRevision()==null||!mapping.targetRevision().matches("[a-f0-9]{64}")||mapping.basis()==null||!BASES.contains(mapping.basis()))
                throw bad(400,"目标账号或历史映射依据不完整，请重新选择");
            if(!unique.add(List.of(mapping.taskId(),mapping.role())))throw bad(400,"重复身份映射");
        }
        mappings.sort(Comparator.comparing(DetectionIdentityService.Mapping::taskId).thenComparing(DetectionIdentityService.Mapping::role));
        var confirmations=new ArrayList<>(command.missingNames()==null?List.<DetectionIdentityService.MissingNameConfirmation>of():command.missingNames());
        if(confirmations.size()>200)throw bad(400,"缺失名称确认数量无效");
        var proofs=new HashMap<List<String>,DetectionIdentityService.MissingNameConfirmation>();
        for(var proof:confirmations){
            if(!missingNameReview||evidence==null||proof==null||proof.taskId()==null||proof.role()==null||!proof.confirmed()||proof.evidenceReference()==null||!proof.evidenceReference().equals(proof.evidenceReference().trim())||!proof.evidenceReference().matches("[\\p{L}\\p{N}][\\p{L}\\p{N}_.:#@ -]{0,127}")||proofs.putIfAbsent(List.of(proof.taskId(),proof.role()),proof)!=null)throw bad(400,"需要每条缺失名称的明确确认和有效资料编号");
        }
        var missingKeys=new HashSet<List<String>>();for(var mapping:mappings)if(mapping.expectedName().isBlank())missingKeys.add(List.of(mapping.taskId(),mapping.role()));
        if(!missingKeys.equals(proofs.keySet()))throw bad(400,"缺失名称确认必须与本次映射逐条对应，不能猜测或套用其他任务依据");
        if(mappings.stream().anyMatch(mapping->mapping.expectedName().isBlank()&&"ACCOUNT_RENAME_VERIFIED".equals(mapping.basis())))throw bad(400,"缺失名称不能以同名或改名关联代替原始资料核实");
        confirmations.sort(Comparator.comparing(DetectionIdentityService.MissingNameConfirmation::taskId).thenComparing(DetectionIdentityService.MissingNameConfirmation::role));
        String protocol=confirmations.isEmpty()?"identity-map-v2":"identity-map-v3";
        var fingerprint=new LinkedHashMap<String,Object>(Map.of("protocol",protocol,"mappings",mappings,"revision",command.revision(),"acknowledgedHistory",true));
        if(!confirmations.isEmpty())fingerprint.put("missingNames",confirmations);
        String digest=hash(fingerprint);
        var control=jdbc.queryForMap("SELECT mode,revision FROM detection_identity_control WHERE control_id=1 FOR UPDATE");
        if(!Set.of("ACTIVE","PREVIEW").contains(Objects.toString(control.get("mode"),"")))throw bad(409,"身份授权模式异常，请先核对");
        var previous=jdbc.queryForList("SELECT actor_user_id,request_sha256,result_json FROM detection_identity_command WHERE request_id=?",command.requestId());
        if(!previous.isEmpty()){
            var old=previous.get(0);
            if(number(old.get("actor_user_id"))!=current.userId()||!digest.equals(old.get("request_sha256")))throw bad(409,"请求编号冲突");
            var replay=result(command.requestId(),true);
            if(!digest.equals(replay.get("digest"))||((Number)replay.get("applied")).intValue()!=mappings.size())throw bad(503,"批次与命令回执不一致，请保留编号核对");
            return replay;
        }
        long revision=((Number)control.get("revision")).longValue();
        if(revision!=command.revision())throw bad(409,"回填版本已变化，请重新预览");
        // Lock targets in stable order, then tasks in stable order. Never resolve a new target by name at commit time.
        var targets=new TreeMap<Long,Account>();
        for(var mapping:mappings){
            var target=new Account(mapping.userId(),mapping.targetUsername(),mapping.targetRole(),mapping.targetRevision());
            var old=targets.putIfAbsent(target.userId(),target);
            if(old!=null&&!old.equals(target))throw bad(409,"同一目标账号包含不同快照");
        }
        for(var target:targets.values())accounts.lock(target);
        var snapshots=new TreeMap<String,Map<String,Object>>();
        for(var mapping:mappings){
            var row=snapshots.computeIfAbsent(mapping.taskId(),id->{
                var found=jdbc.queryForList("SELECT "+FIELDS+" FROM detection_task WHERE task_id=? FOR UPDATE",id);
                if(found.size()!=1)throw bad(409,"历史任务不存在，请重新预览");return found.get(0);
            });
            if(!hash(new TreeMap<>(row)).equals(mapping.snapshot())||!Objects.equals(Objects.toString(row.get(ROLES.get(mapping.role())),""),mapping.expectedName()))
                throw bad(409,"任务身份已变化，请重新预览");
        }
        long appliedRevision=Math.incrementExact(revision);
        var result=new LinkedHashMap<String,Object>();result.put("requestId",command.requestId());result.put("applied",mappings.size());
        result.put("revision",appliedRevision);result.put("digest",digest);result.put("protocol",protocol);
        if(!confirmations.isEmpty())result.put("missingNameCount",confirmations.size());
        String resultJson=encode(result);
        jdbc.update("INSERT INTO detection_identity_mapping_batch(request_id,actor_user_id,actor_name,command_sha256,revision_before,revision_after,applied_count,result_json,created_at) VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",
                command.requestId(),current.userId(),current.username(),digest,revision,appliedRevision,mappings.size(),resultJson);
        long batch=jdbc.queryForObject("SELECT id FROM detection_identity_mapping_batch WHERE request_id=?",Long.class,command.requestId());
        for(var mapping:mappings){
            var before=snapshots.get(mapping.taskId());
            jdbc.update("INSERT INTO detection_identity_mapping_item(batch_id,task_id,identity_role,source_name,source_snapshot,previous_user_id,previous_identity_name,target_user_id,target_username,target_role,target_revision,confirmation_basis) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    batch,mapping.taskId(),mapping.role(),mapping.expectedName(),mapping.snapshot(),before.get(mapping.role()+"_user_id"),before.get(mapping.role()+"_identity_name"),
                    mapping.userId(),mapping.targetUsername(),mapping.targetRole(),mapping.targetRevision(),mapping.basis());
            var proof=proofs.get(List.of(mapping.taskId(),mapping.role()));
            if(proof!=null)jdbc.update("INSERT INTO detection_identity_missing_name_evidence(batch_id,task_id,identity_role,original_name,source_snapshot,target_user_id,evidence_reference) VALUES(?,?,?,?,?,?,?)",batch,mapping.taskId(),mapping.role(),before.get(ROLES.get(mapping.role())),mapping.snapshot(),mapping.userId(),proof.evidenceReference());
            if(jdbc.update("UPDATE detection_task SET "+mapping.role()+"_user_id=?,"+mapping.role()+"_identity_name=? WHERE task_id=?",mapping.userId(),mapping.expectedName(),mapping.taskId())!=1)
                throw bad(409,"任务身份更新未确认");
            if(evidence!=null)evidence.record(mapping.taskId(),mapping.role(),current,proof==null?"SUPERVISOR_MAPPING":"SUPERVISOR_MISSING_NAME",command.requestId(),batch);
            audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","DETECTION_IDENTITY",(proof==null?"MAP_":"MAP_MISSING_NAME_")+mapping.role().toUpperCase(Locale.ROOT),mapping.taskId(),command.requestId(),"APPLIED",appliedRevision));
        }
        if(jdbc.update("UPDATE detection_identity_control SET revision=? WHERE control_id=1 AND revision=?",appliedRevision,revision)!=1)throw bad(409,"回填版本冲突");
        jdbc.update("INSERT INTO detection_identity_command(request_id,actor_user_id,request_sha256,result_json,created_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP(6))",command.requestId(),current.userId(),digest,resultJson);
        result.put("replayed",false);return result;
    }
    /** Read-only business outcome query; absence never authorizes a new command or automatic resubmission. */
    @Transactional(readOnly=true)
    public Map<String,Object> status(AgentActor actor,String requestId){
        supervisor(actor,false);requireEnabled();if(!request(requestId))throw bad(400,"请求编号无效");
        var rows=jdbc.queryForList("SELECT actor_user_id FROM detection_identity_mapping_batch WHERE request_id=?",requestId);
        if(rows.isEmpty())return Map.of("requestId",requestId,"found",false,"state","NOT_RECORDED_YET");
        var data=new LinkedHashMap<>(result(requestId,false));data.put("found",true);data.put("state","COMMITTED");
        var batch=jdbc.queryForMap("SELECT id,actor_user_id,actor_name,created_at FROM detection_identity_mapping_batch WHERE request_id=?",requestId);
        var entries=jdbc.queryForList("SELECT task_id,identity_role,source_name,source_snapshot,previous_user_id,previous_identity_name,target_user_id,target_username,target_role,target_revision,confirmation_basis FROM detection_identity_mapping_item WHERE batch_id=? ORDER BY id",batch.get("id"));
        if("identity-map-v3".equals(data.get("protocol"))){
            var confirmed=jdbc.queryForList("SELECT task_id,identity_role,original_name,source_snapshot,target_user_id,evidence_reference FROM detection_identity_missing_name_evidence WHERE batch_id=?",batch.get("id"));
            if(confirmed.isEmpty())throw bad(503,"缺失名称批次依据不完整，请保留编号核对");
            for(var proof:confirmed){var matching=entries.stream().filter(item->Objects.equals(item.get("task_id"),proof.get("task_id"))&&Objects.equals(item.get("identity_role"),proof.get("identity_role"))&&Objects.equals(item.get("source_snapshot"),proof.get("source_snapshot"))&&Objects.equals(number(item.get("target_user_id")),number(proof.get("target_user_id")))).toList();if(matching.size()!=1)throw bad(503,"缺失名称依据与批次明细不一致");matching.get(0).put("missingNameConfirmation",proof);}
        }
        if(entries.size()!=((Number)data.get("applied")).intValue())throw bad(503,"批次明细数量与回执不一致，请保留编号核对");
        data.put("actorUserId",batch.get("actor_user_id"));data.put("actorName",batch.get("actor_name"));data.put("createdAt",stamp(batch.get("created_at")));data.put("mappings",entries);return data;
    }
    @Transactional(readOnly=true)
    public Map<String,Object> history(AgentActor actor,long before,int size){
        supervisor(actor,false);requireEnabled();if(before<0||size<1||size>30)throw bad(400,"回执分页无效");
        var rows=jdbc.queryForList("SELECT id,request_id,actor_user_id,actor_name,revision_after,applied_count,command_sha256,created_at FROM detection_identity_mapping_batch WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT ?",before,before,size);
        var records=new ArrayList<Map<String,Object>>();
        for(var row:rows)records.add(Map.of("id",row.get("id"),"requestId",row.get("request_id"),"actorUserId",row.get("actor_user_id"),"actorName",row.get("actor_name"),"revision",row.get("revision_after"),"applied",row.get("applied_count"),"digest",row.get("command_sha256"),"createdAt",stamp(row.get("created_at"))));
        return Map.of("records",records,"hasMore",rows.size()==size,"nextCursor",rows.isEmpty()?before:rows.get(rows.size()-1).get("id"));
    }
    private String stamp(Object value){
        java.time.LocalDateTime time=value instanceof java.sql.Timestamp timestamp?timestamp.toLocalDateTime():value instanceof java.time.LocalDateTime local?local:null;
        if(time==null)throw bad(503,"回执时间未能核对");return time.atOffset(java.time.ZoneOffset.ofHours(8)).toString();
    }
    private Map<String,Object> result(String requestId,boolean replayed){
        var rows=jdbc.queryForList("SELECT id,command_sha256,revision_before,revision_after,applied_count,result_json FROM detection_identity_mapping_batch WHERE request_id=?",requestId);
        if(rows.size()!=1)throw bad(409,"历史请求没有 v2 批次回执，请保留编号核对，不自动重新映射");
        var row=rows.get(0);
        long before=((Number)row.get("revision_before")).longValue(),after=((Number)row.get("revision_after")).longValue();
        int count=((Number)row.get("applied_count")).intValue();
        if(before<0||before==Long.MAX_VALUE||after!=before+1||count<1||count>200||!Objects.toString(row.get("command_sha256"),"").matches("[a-f0-9]{64}"))throw bad(503,"批次回执异常，请保留编号核对");
        String protocol;int missingCount;
        try{var saved=json.readTree(row.get("result_json").toString());protocol=saved.path("protocol").asText();missingCount=saved.path("missingNameCount").asInt(0);if(!Set.of("identity-map-v2","identity-map-v3").contains(protocol)||!requestId.equals(saved.path("requestId").asText())||!Objects.equals(row.get("command_sha256"),saved.path("digest").asText())||saved.path("applied").asInt(-1)!=count||saved.path("revision").asLong(-1)!=after||("identity-map-v3".equals(protocol)&&(!missingNameReview||missingCount<1||missingCount>count))||("identity-map-v2".equals(protocol)&&missingCount!=0))throw new IllegalStateException();}catch(Exception error){throw bad(503,"批次协议或持久回执不完整，请保留编号核对");}
        if(missingCount>0){
            Long proofs=jdbc.queryForObject("SELECT COUNT(*) FROM detection_identity_missing_name_evidence WHERE batch_id=?",Long.class,row.get("id"));
            Long matched=jdbc.queryForObject("SELECT COUNT(*) FROM detection_identity_missing_name_evidence p JOIN detection_identity_mapping_item i ON i.batch_id=p.batch_id AND i.task_id=p.task_id AND i.identity_role=p.identity_role AND i.source_snapshot=p.source_snapshot AND i.target_user_id=p.target_user_id AND CAST(i.source_name AS BINARY)=CAST(COALESCE(p.original_name,'') AS BINARY) WHERE p.batch_id=? AND p.evidence_reference<>''",Long.class,row.get("id"));
            if(proofs==null||matched==null||proofs!=missingCount||matched!=missingCount)throw bad(503,"缺失名称确认明细不完整，请保留编号核对，不重新映射");
        }
        var result=new LinkedHashMap<String,Object>(Map.of("requestId",requestId,"applied",row.get("applied_count"),"revision",row.get("revision_after"),"digest",row.get("command_sha256"),"protocol",protocol,"replayed",replayed));
        if(missingCount>0)result.put("missingNameCount",missingCount);return result;
    }
    private String hash(Object value){
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writer(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).writeValueAsBytes(value)));}
        catch(Exception failure){throw new IllegalStateException("身份摘要失败");}
    }
    private String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception failure){throw new IllegalStateException("身份回执保存失败");}}
    @Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY)
    public void lockRequiredAccounts(){
        requireEnabled();
        var ids=new TreeSet<Long>(jdbc.queryForList("SELECT created_user_id FROM detection_task WHERE created_user_id IS NOT NULL UNION SELECT assignee_user_id FROM detection_task WHERE assignee_user_id IS NOT NULL",Long.class));
        for(long id:ids){var account=accounts.describe(id);if(account==null)throw bad(409,"创建人或责任人的原账号已不可用，请重新映射");accounts.lock(account);}
    }
    private static Long number(Object value){return value==null?null:((Number)value).longValue();}
    private static boolean request(String value){return value!=null&&value.matches("[A-Za-z0-9_-]{1,128}");}
    private static ResponseStatusException bad(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
