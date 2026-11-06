package com.ruanzhu.doorhandle.module.app.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.time.LocalDateTime;

/** 本模块持有设置与审计；事务不包含远程 Mem0 调用。 */
@Service
public class MemoryPreferenceService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json=new ObjectMapper().findAndRegisterModules().disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    private final JdbcWorkflowStore workflows;
    private final JdbcAuditStore audits;
    public record PreferenceV1(boolean readEnabled,boolean saveEnabled) {}
    public record PreferenceAuditV1(boolean readEnabled,boolean saveEnabled,LocalDateTime legacyUpdatedAt) {}
    public record MutationV1(String action) {}
    public record MutationAuditV1(boolean legacySnapshot) {}
    private static final WorkflowProtocol<MutationV1> MUTATION=new WorkflowProtocol<>(WorkflowKind.MEMORY_MUTATION,1,MutationV1.class,
            Set.of("PENDING"),Set.of("SUCCEEDED","REJECTED"),Map.of(
            "PENDING",Set.of("DISPATCHED"),"DISPATCHED",Set.of("SUCCEEDED","REJECTED","UNKNOWN"),
            "UNKNOWN",Set.of("SUCCEEDED","REJECTED","UNKNOWN")),value->{
                if(value.action()==null||!Set.of("DELETE","UPDATE","AUTOSAVE","REVIEW_DECISION","LIFECYCLE").contains(value.action()))
                    throw new IllegalArgumentException("Invalid memory mutation action");
            });
    public MemoryPreferenceService(JdbcTemplate jdbc, PlatformTransactionManager manager) {
        this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);
        workflows=new JdbcWorkflowStore(jdbc,json,WorkflowProtocols.defaults().with(MUTATION));
        audits=new JdbcAuditStore(jdbc,json,Map.of("MEMORY_PREFERENCE",PreferenceAuditV1.class,"MEMORY_OPERATION",MutationAuditV1.class));
    }
    public MemoryDtos.Preference get(TenantContext owner) {
        var rows=jdbc.query("SELECT revision,payload_version,payload_json,updated_at FROM runtime_state WHERE namespace='MEMORY_PREFERENCE' AND owner_id=? AND scope_key=''",(rs,n)->{
            if(rs.getInt("payload_version")!=1)throw new IllegalStateException("Unsupported memory preference version");
            var value=decode(rs.getString("payload_json"),PreferenceV1.class);
            return new MemoryDtos.Preference(value.readEnabled(),value.saveEnabled(),Math.toIntExact(rs.getLong("revision")),rs.getString("updated_at"));
        },owner.userId());
        return rows.isEmpty()?new MemoryDtos.Preference(true,true,0,null):rows.get(0);
    }
    public MemoryDtos.Preference change(TenantContext owner, MemoryDtos.ChangePreference request) {
        if(request==null||request.expectedRevision()==null||request.expectedRevision()<0||request.readEnabled()==null||request.saveEnabled()==null)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"记忆设置参数不正确");
        return tx.execute(status->{
            jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,payload_version,payload_json,created_at,updated_at) VALUES('MEMORY_PREFERENCE',?,'',0,1,?,NULL,UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id)",owner.userId(),encode(new PreferenceV1(true,true)));
            if(jdbc.update("UPDATE runtime_state SET payload_json=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE namespace='MEMORY_PREFERENCE' AND owner_id=? AND scope_key='' AND revision=?",encode(new PreferenceV1(request.readEnabled(),request.saveEnabled())),owner.userId(),request.expectedRevision())!=1)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"记忆设置已更新，请刷新后重试");
            var saved=get(owner);
            audits.appendMemoryPreference(new AuditEvent("MEMORY_PREFERENCE",owner.userId(),owner.userId(),"MEMORY_PREFERENCE",Long.toString(owner.userId()),null,null,null,null,
                    "PREFERENCE_CHANGED",(long)saved.revision(),null,null,1,new PreferenceAuditV1(saved.readEnabled(),saved.saveEnabled(),null)));
            return saved;
        });
    }
    /** true 表示已执行相同操作；其他未决或失败请求不自动重放远程副作用。 */
    public boolean reserveDelete(TenantContext owner, String memoryId, MemoryDtos.Delete request) {
        return reserveMutation(owner,memoryId,"DELETE",request.requestId(),request.expectedDigest());
    }
    public boolean reserveUpdate(TenantContext owner, String memoryId, MemoryDtos.Update request) {
        // 同一请求键必须绑定原版本和目标正文，只保存摘要，不把私人正文写入审计。
        String fingerprint;
        try {
            fingerprint=java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256")
                    .digest((request.expectedDigest()+"\n"+request.memory()).getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch(java.security.NoSuchAlgorithmException error) { throw new IllegalStateException("SHA-256 unavailable",error); }
        return reserveMutation(owner,memoryId,"UPDATE",request.requestId(),fingerprint);
    }
    public boolean reserveAutomatic(TenantContext owner,String requestId,String fingerprint) {
        return reserveMutation(owner,null,"AUTOSAVE",requestId,fingerprint);
    }
    private String reviewFingerprint(String reviewId,int revision,String candidate,String choice){
        try{return java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest((reviewId+"|"+revision+"|"+candidate+"|"+choice).getBytes(java.nio.charset.StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
    public boolean reserveReviewDecision(TenantContext owner,String source,String reviewId,MemoryDtos.ResolveReview request){
        return reserveMutation(owner,source,"REVIEW_DECISION",request.requestId(),reviewFingerprint(reviewId,request.expectedRevision(),request.candidateId(),request.choice()));
    }
    public void reconcileReviewDecisions(TenantContext owner,MemoryDtos.Review review){
        tx.executeWithoutResult(status->{
            JdbcOwnerLock.lock(jdbc,JdbcOwnerLock.Scope.MEMORY_MUTATION,owner.userId());
            for(var decision:review.decisions()) {
                var row=workflows.findByRequestLocked(WorkflowKind.MEMORY_MUTATION,"OWNER:"+owner.userId(),decision.requestId());
                if(row.isPresent()&&matches(row.get(),"REVIEW_DECISION",review.sourceId(),reviewFingerprint(review.id(),decision.expectedRevision(),decision.candidateId(),decision.choice()))
                        &&Set.of("DISPATCHED","UNKNOWN").contains(row.get().status()))transition(row.get(),"SUCCEEDED");
            }
        });
    }
    public void requireReviewDecision(TenantContext owner,MemoryDtos.Review review,MemoryDtos.ReviewDecision decision){
        var row=workflows.findByRequest(WorkflowKind.MEMORY_MUTATION,"OWNER:"+owner.userId(),decision.requestId());
        if(row.isEmpty()||!"SUCCEEDED".equals(row.get().status())||!matches(row.get(),"REVIEW_DECISION",review.sourceId(),reviewFingerprint(review.id(),decision.expectedRevision(),decision.candidateId(),decision.choice())))
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"审阅决定的审计结果需要核对");
        requireAudit(row.get());
    }
    public boolean reserveLifecycle(TenantContext owner,String memoryId,MemoryDtos.ChangeLifecycle request) {
        try {
            String value=request.expectedDigest()+"|"+request.expectedRevision()+"|"+request.state()+"|"+request.expiresAt()+"|"+request.autoDelete();
            String digest=java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
            return reserveMutation(owner,memoryId,"LIFECYCLE",request.requestId(),digest);
        }catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
    public String automaticOutcome(TenantContext owner,String requestId) {
        var row=workflows.findByRequest(WorkflowKind.MEMORY_MUTATION,"OWNER:"+owner.userId(),requestId);
        if(row.isEmpty()||!"AUTOSAVE".equals(workflows.payload(row.get(),MutationV1.class).action()))throw new ResponseStatusException(HttpStatus.NOT_FOUND,"提炼记录不存在或无权限");
        requireAudit(row.get());return row.get().status();
    }
    public void reconcileAutomatic(TenantContext owner,String requestId,String state) {
        tx.executeWithoutResult(status->{
            JdbcOwnerLock.lock(jdbc,JdbcOwnerLock.Scope.MEMORY_MUTATION,owner.userId());
            var row=workflows.findByRequestLocked(WorkflowKind.MEMORY_MUTATION,"OWNER:"+owner.userId(),requestId).orElseThrow(()->new ResponseStatusException(HttpStatus.NOT_FOUND,"提炼记录不存在或无权限"));
            if(!"AUTOSAVE".equals(workflows.payload(row,MutationV1.class).action()))throw new ResponseStatusException(HttpStatus.NOT_FOUND,"提炼记录不存在或无权限");
            requireAudit(row);
            String outcome="SUCCEEDED".equals(state)?"SUCCEEDED":"NOT_STARTED".equals(state)?"REJECTED":"NEEDS_REVIEW".equals(state)?"UNKNOWN":null;
            if(outcome!=null&&Set.of("DISPATCHED","UNKNOWN").contains(row.status())&&!outcome.equals(row.status()))transition(row,outcome);
        });
    }
    private boolean reserveMutation(TenantContext owner,String memoryId,String action,String requestId,String fingerprint) {
        return Boolean.TRUE.equals(tx.execute(status->{
            JdbcOwnerLock.lock(jdbc,JdbcOwnerLock.Scope.MEMORY_MUTATION,owner.userId());
            var row=workflows.findByRequestLocked(WorkflowKind.MEMORY_MUTATION,"OWNER:"+owner.userId(),requestId)
                    .orElseGet(()->workflows.create(new WorkflowDraft(UUID.randomUUID().toString(),WorkflowKind.MEMORY_MUTATION,"OWNER:"+owner.userId(),requestId,fingerprint,
                            owner.userId(),owner.userId(),null,"MEMORY",memoryId,null,null,null,"PENDING",null,1,new MutationV1(action))));
            if(!matches(row,action,memoryId,fingerprint))throw new ResponseStatusException(HttpStatus.CONFLICT,"请求编号已用于其他操作、记忆或内容版本");
            if("SUCCEEDED".equals(row.status())){requireAudit(row);return true;}
            if(!"PENDING".equals(row.status()))throw new ResponseStatusException(HttpStatus.CONFLICT,"上次操作结果需要核对，请刷新后再操作");
            transition(row,"DISPATCHED");
            return false;
        }));
    }
    public void deletionOutcome(TenantContext owner,String requestId,String outcome) {
        if(!java.util.Set.of("SUCCEEDED","REJECTED","UNKNOWN").contains(outcome))throw new IllegalArgumentException("invalid outcome");
        tx.executeWithoutResult(status->{
            JdbcOwnerLock.lock(jdbc,JdbcOwnerLock.Scope.MEMORY_MUTATION,owner.userId());
            var row=workflows.findByRequestLocked(WorkflowKind.MEMORY_MUTATION,"OWNER:"+owner.userId(),requestId);
            if(row.isEmpty()||!"DISPATCHED".equals(row.get().status()))throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"操作结果待核对，请刷新记忆列表");
            transition(row.get(),outcome);
        });
    }
    public List<MemoryDtos.Audit> audit(TenantContext owner) {
        return jdbc.query("""
                SELECT a.id,a.kind,a.action,a.outcome,a.revision,a.payload_version,a.payload_json,a.request_id,
                    w.resource_id AS memory_id,COALESCE(w.created_at,a.occurred_at) AS created_at,
                    COALESCE(w.updated_at,a.occurred_at) AS updated_at
                FROM audit_event a LEFT JOIN workflow_instance w ON a.kind='MEMORY_OPERATION'
                    AND w.kind='MEMORY_MUTATION' AND w.workflow_id=a.resource_id AND w.owner_user_id=a.owner_user_id
                WHERE a.owner_user_id=? AND a.kind IN ('MEMORY_PREFERENCE','MEMORY_OPERATION')
                    AND NOT EXISTS(SELECT 1 FROM audit_event newer WHERE a.kind='MEMORY_OPERATION'
                        AND newer.kind=a.kind AND newer.owner_user_id=a.owner_user_id AND newer.resource_id=a.resource_id
                        AND (newer.revision>a.revision OR newer.revision=a.revision AND newer.id>a.id))
                ORDER BY a.id DESC LIMIT 50
                """,(rs,n)->{
            if(rs.getInt("payload_version")!=1)throw new IllegalStateException("Unsupported memory audit version");
            var preference="MEMORY_PREFERENCE".equals(rs.getString("kind"))?decode(rs.getString("payload_json"),PreferenceAuditV1.class):null;
            return new MemoryDtos.Audit(rs.getLong("id"),rs.getString("action"),rs.getString("outcome"),rs.getString("memory_id"),
                    preference==null?null:Math.toIntExact(rs.getLong("revision")),preference==null?null:preference.readEnabled(),preference==null?null:preference.saveEnabled(),
                    rs.getString("created_at"),preference!=null&&preference.legacyUpdatedAt()!=null?preference.legacyUpdatedAt().toString():rs.getString("updated_at"),rs.getString("request_id"));
        },owner.userId());
    }
    private boolean matches(WorkflowRecord row,String action,String memoryId,String fingerprint) {
        return action.equals(workflows.payload(row,MutationV1.class).action())&&java.util.Objects.equals(memoryId,row.resourceId())&&fingerprint.equals(row.requestSha256());
    }
    private void transition(WorkflowRecord before,String outcome) {
        var after=workflows.transition(before,outcome,workflows.payload(before,MutationV1.class),null,null,null);
        audits.appendMemoryOperation(new AuditEvent("MEMORY_OPERATION",after.ownerUserId(),after.actorUserId(),"MEMORY_MUTATION",after.workflowId(),null,null,null,after.requestId(),
                workflows.payload(after,MutationV1.class).action(),after.revision(),after.requestSha256(),after.updatedAt(),1,new MutationAuditV1(false)),outcome);
    }
    private void requireAudit(WorkflowRecord row) {
        if(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='MEMORY_OPERATION' AND owner_user_id=? AND resource_id=? AND revision=? AND outcome=? AND content_sha256=?",Long.class,
                row.ownerUserId(),row.workflowId(),row.revision(),row.status(),row.requestSha256())!=1)
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"操作结果的审计回执需要核对");
    }
    private String encode(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("Cannot encode memory protocol",error);}}
    private <T> T decode(String value,Class<T> type){try{return json.readValue(value,type);}catch(Exception error){throw new IllegalStateException("Invalid stored memory protocol",error);}}
}
