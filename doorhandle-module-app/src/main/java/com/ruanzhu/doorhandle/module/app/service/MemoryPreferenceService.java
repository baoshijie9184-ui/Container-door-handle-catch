package com.ruanzhu.doorhandle.module.app.service;

import com.ruanzhu.doorhandle.module.app.dto.chat.MemoryDtos;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.util.List;

/** 本模块持有设置与审计；事务不包含远程 Mem0 调用。 */
@Service
public class MemoryPreferenceService {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    public MemoryPreferenceService(JdbcTemplate jdbc, PlatformTransactionManager manager) { this.jdbc=jdbc;this.tx=new TransactionTemplate(manager); }
    public MemoryDtos.Preference get(TenantContext owner) {
        var rows=jdbc.query("SELECT * FROM agent_memory_preference WHERE owner_user_id=?",(rs,n)->new MemoryDtos.Preference(rs.getBoolean("read_enabled"),rs.getBoolean("save_enabled"),rs.getInt("revision"),rs.getString("updated_at")),owner.userId());
        return rows.isEmpty()?new MemoryDtos.Preference(true,true,0,null):rows.get(0);
    }
    public MemoryDtos.Preference change(TenantContext owner, MemoryDtos.ChangePreference request) {
        if(request==null||request.expectedRevision()==null||request.expectedRevision()<0||request.readEnabled()==null||request.saveEnabled()==null)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"记忆设置参数不正确");
        return tx.execute(status->{
            jdbc.update("INSERT IGNORE INTO agent_memory_preference(owner_user_id,read_enabled,save_enabled,revision,updated_at) VALUES(?,TRUE,TRUE,0,CURRENT_TIMESTAMP)",owner.userId());
            if(jdbc.update("UPDATE agent_memory_preference SET read_enabled=?,save_enabled=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND revision=?",request.readEnabled(),request.saveEnabled(),owner.userId(),request.expectedRevision())!=1)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"记忆设置已更新，请刷新后重试");
            var saved=get(owner);
            jdbc.update("INSERT INTO agent_memory_audit(owner_user_id,action_name,outcome,preference_revision,read_enabled,save_enabled,created_at,updated_at) VALUES(?,'PREFERENCE_CHANGED','SUCCEEDED',?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",owner.userId(),saved.revision(),saved.readEnabled(),saved.saveEnabled());
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
        for(var decision:review.decisions())jdbc.update("UPDATE agent_memory_audit SET outcome='SUCCEEDED',updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_key=? AND action_name='REVIEW_DECISION' AND memory_id=? AND content_digest=? AND outcome IN ('DISPATCHED','UNKNOWN')",
            owner.userId(),decision.requestId(),review.sourceId(),reviewFingerprint(review.id(),decision.expectedRevision(),decision.candidateId(),decision.choice()));
    }
    public void requireReviewDecision(TenantContext owner,MemoryDtos.Review review,MemoryDtos.ReviewDecision decision){
        Integer count=jdbc.queryForObject("SELECT COUNT(*) FROM agent_memory_audit WHERE owner_user_id=? AND request_key=? AND action_name='REVIEW_DECISION' AND memory_id=? AND content_digest=? AND outcome='SUCCEEDED'",Integer.class,
            owner.userId(),decision.requestId(),review.sourceId(),reviewFingerprint(review.id(),decision.expectedRevision(),decision.candidateId(),decision.choice()));
        if(count==null||count!=1)throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"审阅决定的审计结果需要核对");
    }
    public boolean reserveLifecycle(TenantContext owner,String memoryId,MemoryDtos.ChangeLifecycle request) {
        try {
            String value=request.expectedDigest()+"|"+request.expectedRevision()+"|"+request.state()+"|"+request.expiresAt()+"|"+request.autoDelete();
            String digest=java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
            return reserveMutation(owner,memoryId,"LIFECYCLE",request.requestId(),digest);
        }catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
    public String automaticOutcome(TenantContext owner,String requestId) {
        var rows=jdbc.queryForList("SELECT outcome FROM agent_memory_audit WHERE owner_user_id=? AND request_key=? AND action_name='AUTOSAVE'",owner.userId(),requestId);
        if(rows.size()!=1)throw new ResponseStatusException(HttpStatus.NOT_FOUND,"提炼记录不存在或无权限");
        return (String)rows.get(0).get("outcome");
    }
    public void reconcileAutomatic(TenantContext owner,String requestId,String state) {
        automaticOutcome(owner,requestId);
        if("SUCCEEDED".equals(state))jdbc.update("UPDATE agent_memory_audit SET outcome='SUCCEEDED',updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_key=? AND action_name='AUTOSAVE' AND outcome IN ('DISPATCHED','UNKNOWN')",owner.userId(),requestId);
        else if("NEEDS_REVIEW".equals(state)||"NOT_STARTED".equals(state))jdbc.update("UPDATE agent_memory_audit SET outcome=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_key=? AND action_name='AUTOSAVE' AND outcome IN ('DISPATCHED','UNKNOWN')","NOT_STARTED".equals(state)?"REJECTED":"UNKNOWN",owner.userId(),requestId);
    }
    private boolean reserveMutation(TenantContext owner,String memoryId,String action,String requestId,String fingerprint) {
        return Boolean.TRUE.equals(tx.execute(status->{
            jdbc.update("INSERT IGNORE INTO agent_memory_audit(owner_user_id,action_name,outcome,request_key,memory_id,content_digest,created_at,updated_at) VALUES(?,?,'PENDING',?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",owner.userId(),action,requestId,memoryId,fingerprint);
            var rows=jdbc.queryForList("SELECT action_name,memory_id,content_digest,outcome FROM agent_memory_audit WHERE owner_user_id=? AND request_key=? FOR UPDATE",owner.userId(),requestId);
            if(rows.size()!=1)throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"记忆操作审计暂不可用");
            var row=rows.get(0);
            if(!action.equals(row.get("action_name"))||!java.util.Objects.equals(memoryId,row.get("memory_id"))||!fingerprint.equals(row.get("content_digest")))throw new ResponseStatusException(HttpStatus.CONFLICT,"请求编号已用于其他操作、记忆或内容版本");
            if("SUCCEEDED".equals(row.get("outcome")))return true;
            if(!"PENDING".equals(row.get("outcome")))throw new ResponseStatusException(HttpStatus.CONFLICT,"上次操作结果需要核对，请刷新后再操作");
            if(jdbc.update("UPDATE agent_memory_audit SET outcome='DISPATCHED',updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_key=? AND outcome='PENDING'",owner.userId(),requestId)!=1)
                throw new ResponseStatusException(HttpStatus.CONFLICT,"此记忆请求正在处理");
            return false;
        }));
    }
    public void deletionOutcome(TenantContext owner,String requestId,String outcome) {
        if(!java.util.Set.of("SUCCEEDED","REJECTED","UNKNOWN").contains(outcome))throw new IllegalArgumentException("invalid outcome");
        if(jdbc.update("UPDATE agent_memory_audit SET outcome=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_key=? AND outcome='DISPATCHED'",outcome,owner.userId(),requestId)!=1)
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"操作结果待核对，请刷新记忆列表");
    }
    public List<MemoryDtos.Audit> audit(TenantContext owner) {
        return jdbc.query("SELECT * FROM agent_memory_audit WHERE owner_user_id=? ORDER BY id DESC LIMIT 50",(rs,n)->new MemoryDtos.Audit(rs.getLong("id"),rs.getString("action_name"),rs.getString("outcome"),rs.getString("memory_id"),(Integer)rs.getObject("preference_revision"),rs.getObject("read_enabled",Boolean.class),rs.getObject("save_enabled",Boolean.class),rs.getString("created_at"),rs.getString("updated_at"),rs.getString("request_key")),owner.userId());
    }
}
