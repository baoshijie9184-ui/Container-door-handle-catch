package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.*;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.*;

/** Immutable install snapshots, rollback references, quota reservation and explicitly requested cleanup. */
public final class FetchInstallationLifecycle {
    private final long reservation;
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final ObjectMapper json;
    private final FetchMcpRuntime runtime;private final FetchInstallationStorage storage;private final long quota;
    private final McpInstallWorkerEvidence workers;
    public FetchInstallationLifecycle(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,FetchMcpRuntime runtime,Path workspace,long quota){
        this(jdbc,manager,json,runtime,workspace,quota,null);
    }
    public FetchInstallationLifecycle(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,FetchMcpRuntime runtime,Path workspace,long quota,McpInstallWorkerEvidence workers){
        this.jdbc=jdbc;this.runtime=runtime;this.storage=new FetchInstallationStorage(workspace);this.quota=quota;this.json=json.copy().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);this.workers=workers;
        reservation=runtime.installationReservationBytes();if(quota<reservation||quota>4L*1024*1024*1024)throw new IllegalArgumentException("MCP_STORAGE_QUOTA_INVALID");
        tx=new TransactionTemplate(manager);tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);tx.setTimeout(15);
    }
    public void schema(){jdbc.queryForList("SELECT installation_id,reconcile_request,writer_evidence_code,reserved_bytes FROM agent_fetch_installation WHERE 1=0");jdbc.queryForList("SELECT request_id FROM agent_fetch_lifecycle_command WHERE 1=0");if(workers!=null)workers.schema();}
    public McpInstallWorkerEvidence.Capture prepareWorker(AgentActor actor,String operation){return workers==null?null:workers.capture(storage.directory(actor.userId(),operation));}
    public void workerDispatched(AgentActor actor,String operation,McpInstallWorkerEvidence.Capture capture){if(workers!=null)workers.dispatched(actor,operation,capture);}
    public void requireUsable(long owner,String operation){
        var rows=jdbc.queryForList("SELECT writer_exit_verified,transport FROM agent_fetch_installation WHERE owner_user_id=? AND installation_id=?",owner,operation);
        if(runtime.nativeInstallSupervised()&&(rows.isEmpty()||!flag(rows.get(0).get("writer_exit_verified"))))throw fail(409,"请先核对本地安装写入及连接检查进程退出 再启用或调用");
    }
    /** Called while the existing registration row is locked, in the install transaction. */
    public void begin(AgentActor actor,Map<String,Object> row,String operation){
        runtime.requireImageUsable(runtime.targetImage());
        remember(actor,row);
        var reserved=unsettled(actor.userId());var usage=usage(actor.userId(),reserved);
        if(runtime.nativeInstallSupervised()&&!reserved.isEmpty())throw fail(409,"请先核对原安装写入者 再开始新的本地安装");
        if(Math.addExact(usage.bytes(),Math.addExact(reservedBytes(actor.userId()),reservation))>quota)throw fail(409,"本人 MCP 存储额度不足 请先清理无引用安装");
        String prior="INSTALLED".equals(row.get("status"))?(String)row.get("operation_id"):null;
        jdbc.update("INSERT INTO agent_fetch_installation(owner_user_id,installation_id,prior_installation_id,state,package_version,transport,reserved_bytes,image_id) VALUES(?,?,?,'INSTALLING',?,?,?,?)",actor.userId(),operation,prior,FetchMcpRuntime.VERSION,runtime.transport(),reservation,runtime.targetImage());
        if(prior!=null){jdbc.update("UPDATE agent_fetch_installation SET retained_for_rollback=FALSE,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND retained_for_rollback=TRUE",actor.userId());jdbc.update("UPDATE agent_fetch_installation SET retained_for_rollback=TRUE,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND installation_id=?",actor.userId(),prior);}
        audit(actor,"VERSION_PREPARE","STARTED",operation,Map.of("hasPrevious",prior!=null,"reservedBytes",reservation));
    }
    private void remember(AgentActor actor,Map<String,Object> row){
        if(!"INSTALLED".equals(row.get("status"))||row.get("operation_id")==null||row.get("manifest_json")==null)return;
        var manifest=read(row.get("manifest_json"));String encoded=write(manifest);if(!hash(encoded).equals(row.get("manifest_sha256")))throw fail(409,"当前 MCP 版本摘要无法核对");
        var existing=jdbc.queryForList("SELECT state,manifest_sha256 FROM agent_fetch_installation WHERE owner_user_id=? AND installation_id=?",actor.userId(),row.get("operation_id"));
        if(!existing.isEmpty()&&(!"READY".equals(existing.get(0).get("state"))||!hash(encoded).equals(existing.get(0).get("manifest_sha256"))))throw fail(409,"当前登记与已保存的不可变版本不一致");
        jdbc.update("INSERT INTO agent_fetch_installation(owner_user_id,installation_id,state,package_version,transport,image_id,manifest_json,manifest_sha256) VALUES(?,?,'READY',?,?,?,?,?) ON DUPLICATE KEY UPDATE installation_id=VALUES(installation_id)",actor.userId(),row.get("operation_id"),manifest.get("version"),manifest.get("transport"),manifest.get("image"),encoded,hash(encoded));
    }
    public void rememberRemoved(AgentActor actor,Map<String,Object> row){remember(actor,row);jdbc.update("UPDATE agent_fetch_installation SET retained_for_rollback=FALSE,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND installation_id=? AND retained_for_rollback=TRUE",actor.userId(),row.get("operation_id"));}
    /** The caller has validated the fixed manifest and still owns the install lease. */
    public void succeeded(AgentActor actor,String operation,Map<String,Object> manifest){
        String encoded=write(manifest);
        if(jdbc.update("UPDATE agent_fetch_installation SET state='READY',writer_exit_verified=?,manifest_json=?,manifest_sha256=?,image_id=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND installation_id=? AND state='INSTALLING'",!runtime.nativeInstallSupervised(),encoded,hash(encoded),manifest.get("image"),actor.userId(),operation)!=1)throw fail(409,"MCP 版本准备已失效");
        audit(actor,"VERSION_PREPARE","SUCCEEDED",operation,Map.of("version",FetchMcpRuntime.VERSION,"enabled",false));
    }
    /** Restores the previous immutable registration, always disabled. No old tool is automatically invoked. */
    public boolean failed(AgentActor actor,String operation,String code){
        jdbc.update("UPDATE agent_fetch_installation SET state=CASE WHEN writer_exit_verified=TRUE THEN 'CACHED' ELSE 'NEEDS_REVIEW' END,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND installation_id=? AND state='INSTALLING'",actor.userId(),operation);
        var rows=jdbc.queryForList("SELECT prior_installation_id FROM agent_fetch_installation WHERE owner_user_id=? AND installation_id=?",actor.userId(),operation);
        if(rows.isEmpty()||rows.get(0).get("prior_installation_id")==null)return false;
        String previous=(String)rows.get(0).get("prior_installation_id");var snapshot=snapshot(actor,previous);if(!"READY".equals(snapshot.get("state"))||snapshot.get("manifest_json")==null)return false;
        var manifest=read(snapshot.get("manifest_json"));if(!hash(write(manifest)).equals(snapshot.get("manifest_sha256")))throw fail(409,"上一 MCP 版本快照无法核对");
        jdbc.update("UPDATE agent_local_mcp SET status='INSTALLED',enabled=FALSE,package_version=?,operation_id=?,manifest_json=?,manifest_sha256=?,lease_expires_at=NULL,error_code=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND server_key='fetch' AND operation_id=?",snapshot.get("package_version"),previous,write(manifest),snapshot.get("manifest_sha256"),code,actor.userId(),operation);
        audit(actor,"VERSION_FALLBACK","DISABLED",previous,Map.of("failedInstallation",operation,"errorCode",code));return true;
    }
    /** Runs only after the installer callable actually returns, not Future.cancel()/isDone(). */
    public void writerStopped(AgentActor actor,String operation){
        if(workers!=null)tx.executeWithoutResult(status->{registration(actor);workers.returned(actor,operation);});
        var proof=workers==null?new McpInstallWorkerEvidence.Proof(!runtime.nativeInstallSupervised(),"WRITER_RETURNED"):workers.proof(actor,operation,storage.directory(actor.userId(),operation));
        tx.executeWithoutResult(status->{registration(actor);recordWriterProof(actor,operation,proof);});
    }
    /** Only called under the registration lock after a QUEUED job was revoked before claim. */
    public void neverDispatched(AgentActor actor,String operation){
        Long count=jdbc.queryForObject("SELECT COUNT(*) FROM agent_mcp_install_worker WHERE owner_user_id=? AND installation_id=?",Long.class,actor.userId(),operation);
        if(count!=null&&count==0)recordWriterProof(actor,operation,new McpInstallWorkerEvidence.Proof(true,"INSTALL_NEVER_DISPATCHED"));
    }
    private void recordWriterProof(AgentActor actor,String operation,McpInstallWorkerEvidence.Proof proof){
        var row=snapshot(actor,operation);boolean verified=flag(row.get("writer_exit_verified"))||proof.verified()&&!hasPending(actor,operation);
        String code=verified?flag(row.get("writer_exit_verified"))?Objects.toString(row.get("writer_evidence_code"),proof.code()):proof.code():proof.verified()?"INSTALL_PROBE_EXIT_UNVERIFIED":proof.code();
        jdbc.update("UPDATE agent_fetch_installation SET writer_exit_verified=?,writer_evidence_code=?,state=CASE WHEN state='NEEDS_REVIEW' AND ?=TRUE THEN 'CACHED' ELSE state END,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",verified,code,verified,row.get("id"));
        audit(actor,"INSTALL_WRITER_EXIT",verified?"VERIFIED":"NEEDS_REVIEW",operation,Map.of("writerExitVerified",verified,"evidenceCode",code));
    }
    public void reconcileWriter(AgentActor actor,String operation,int expected,String request){
        if(workers==null)throw fail(409,"安装执行核对尚未启用");String fingerprint=hash("RECONCILE_INSTALL:"+operation+":"+expected);
        boolean claimed=Boolean.TRUE.equals(tx.execute(status->{
            var registration=registration(actor);if(duplicate(actor,request,fingerprint))return false;var candidate=snapshot(actor,operation);
            if(number(candidate,"revision")!=expected||flag(candidate.get("writer_exit_verified"))||!Set.of("NEEDS_REVIEW","READY").contains(candidate.get("state")))throw fail(409,"安装退出状态已变化 请刷新");
            if("INSTALLING".equals(registration.get("status"))&&operation.equals(registration.get("operation_id")))throw fail(409,"请先取消活动安装 再核对退出");
            if(jdbc.queryForObject("SELECT COUNT(*) FROM agent_fetch_installation WHERE id=? AND reconcile_expires_at>CURRENT_TIMESTAMP",Long.class,candidate.get("id"))>0)throw fail(409,"安装退出正在核对 请稍后刷新");
            command(actor,request,operation,"RECONCILE_INSTALL",fingerprint,"STARTED");
            jdbc.update("UPDATE agent_fetch_installation SET reconcile_request=?,reconcile_expires_at=DATE_ADD(CURRENT_TIMESTAMP,INTERVAL 90 SECOND),revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",request,candidate.get("id"));
            audit(actor,"INSTALL_EXIT_RECONCILE","STARTED",operation,Map.of("requestId",request));return true;
        }));
        if(!claimed)return;
        McpInstallWorkerEvidence.Proof proof;
        try{proof=workers.proof(actor,operation,storage.directory(actor.userId(),operation));}catch(RuntimeException error){proof=new McpInstallWorkerEvidence.Proof(false,"CONTROLLER_PROOF_UNAVAILABLE");}
        var observed=proof;tx.executeWithoutResult(status->{
            registration(actor);var candidate=snapshot(actor,operation);if(!request.equals(candidate.get("reconcile_request")))return;
            boolean verified=observed.verified()&&!hasPending(actor,operation)||flag(candidate.get("writer_exit_verified"));String code=flag(candidate.get("writer_exit_verified"))?Objects.toString(candidate.get("writer_evidence_code"),observed.code()):observed.verified()&&!verified?"INSTALL_PROBE_EXIT_UNVERIFIED":observed.code();
            jdbc.update("UPDATE agent_fetch_installation SET writer_exit_verified=?,writer_evidence_code=?,state=CASE WHEN state='NEEDS_REVIEW' AND ?=TRUE THEN 'CACHED' ELSE state END,reconcile_expires_at=NULL,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",verified,code,verified,candidate.get("id"));
            jdbc.update("UPDATE agent_fetch_lifecycle_command SET status=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_id=?",verified?"COMPLETED":"NEEDS_REVIEW",actor.userId(),request);
            audit(actor,"INSTALL_EXIT_RECONCILE",verified?"VERIFIED":"NEEDS_REVIEW",operation,Map.of("requestId",request,"writerExitVerified",verified,"evidenceCode",code));
        });
    }
    public void rollback(AgentActor actor,String operation,int expected,String request){tx.executeWithoutResult(status->{
        var registration=registration(actor);String fingerprint=hash("ROLLBACK:"+operation+":"+expected);if(duplicate(actor,request,fingerprint))return;
        if(number(registration,"revision")!=expected||"INSTALLING".equals(registration.get("status")))throw fail(409,"MCP 状态已变化 请刷新核对");
        requireNoPending(actor,null);var candidate=snapshot(actor,operation);
        if("STDIO".equals(candidate.get("transport"))&&!flag(candidate.get("writer_exit_verified")))throw fail(409,"本地版本写入者退出尚未核实 不能回退");
        if(!flag(candidate.get("retained_for_rollback"))||!"READY".equals(candidate.get("state"))||operation.equals(registration.get("operation_id")))throw fail(409,"此版本未保留为可回退版本");
        var manifest=read(candidate.get("manifest_json"));if(!hash(write(manifest)).equals(candidate.get("manifest_sha256")))throw fail(409,"版本快照摘要无法核对");
        try{runtime.validate(storage.directory(actor.userId(),operation),manifest);}catch(Exception error){throw fail(409,"回退版本不在已批准发布范围或文件无法核对");}
        remember(actor,registration);command(actor,request,operation,"ROLLBACK",fingerprint,"COMPLETED");
        jdbc.update("UPDATE agent_fetch_installation SET retained_for_rollback=FALSE,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND retained_for_rollback=TRUE",actor.userId());
        if(registration.get("operation_id")!=null)jdbc.update("UPDATE agent_fetch_installation SET retained_for_rollback=TRUE,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND installation_id=? AND state='READY'",actor.userId(),registration.get("operation_id"));
        jdbc.update("UPDATE agent_local_mcp SET status='INSTALLED',enabled=FALSE,operation_id=?,package_version=?,manifest_json=?,manifest_sha256=?,lease_expires_at=NULL,error_code=NULL,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",operation,candidate.get("package_version"),write(manifest),candidate.get("manifest_sha256"),registration.get("id"));
        audit(actor,"VERSION_ROLLBACK","DISABLED",operation,Map.of("requestId",request,"enabled",false));
    });}
    public void cleanup(AgentActor actor,String operation,int expected,String request){
        String fingerprint=hash("CLEANUP:"+operation+":"+expected);
        boolean claimed=Boolean.TRUE.equals(tx.execute(status->{
            var registration=registration(actor);if(duplicate(actor,request,fingerprint))return false;
            var candidate=snapshot(actor,operation);if(number(candidate,"revision")!=expected)throw fail(409,"安装文件状态已变化 请刷新");
            if(operation.equals(registration.get("operation_id"))&&Set.of("INSTALLED","INSTALLING").contains(registration.get("status"))||flag(candidate.get("retained_for_rollback")))throw fail(409,"当前或回退版本仍被引用 不允许清理");
            if(!flag(candidate.get("writer_exit_verified"))||Set.of("INSTALLING","REMOVED").contains(candidate.get("state")))throw fail(409,"安装执行退出尚未核实或文件已清理");
            if("CLEANING".equals(candidate.get("state"))&&!flag(candidate.get("cleanup_expired")))throw fail(409,"此安装正在清理 请稍后刷新");
            requireNoPending(actor,operation);command(actor,request,operation,"CLEANUP",fingerprint,"STARTED");
            jdbc.update("UPDATE agent_fetch_installation SET state='CLEANING',cleanup_request=?,cleanup_expires_at=DATE_ADD(CURRENT_TIMESTAMP,INTERVAL 90 SECOND),revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",request,candidate.get("id"));
            audit(actor,"STORAGE_CLEANUP","STARTED",operation,Map.of("requestId",request));return true;
        }));
        if(!claimed)return;boolean removed;
        try{storage.remove(actor.userId(),operation);removed=true;}catch(Exception error){removed=false;}
        boolean complete=removed;
        tx.executeWithoutResult(status->{registration(actor);var candidate=snapshot(actor,operation);if(!request.equals(candidate.get("cleanup_request")))return;
            jdbc.update("UPDATE agent_fetch_installation SET state=?,revision=revision+1,cleanup_expires_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",complete?"REMOVED":"CLEANUP_REVIEW",candidate.get("id"));
            jdbc.update("UPDATE agent_fetch_lifecycle_command SET status=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_id=?",complete?"COMPLETED":"NEEDS_REVIEW",actor.userId(),request);
            audit(actor,"STORAGE_CLEANUP",complete?"COMPLETED":"NEEDS_REVIEW",operation,Map.of("requestId",request,"directoryRemoved",complete,"sharedImagesRemoved",false));
        });
    }
    public void releaseRetention(AgentActor actor,String operation,int expected,String request){tx.executeWithoutResult(status->{
        var registration=registration(actor);String fingerprint=hash("RELEASE_RETENTION:"+operation+":"+expected);if(duplicate(actor,request,fingerprint))return;
        var candidate=snapshot(actor,operation);
        if(number(candidate,"revision")!=expected||!flag(candidate.get("retained_for_rollback")))throw fail(409,"回退保留状态已变化 请刷新");
        if("INSTALLING".equals(registration.get("status"))||operation.equals(registration.get("operation_id"))&&"INSTALLED".equals(registration.get("status")))throw fail(409,"当前版本或升级中的回退引用不能解除");
        requireNoPending(actor,operation);command(actor,request,operation,"RELEASE_RETENTION",fingerprint,"COMPLETED");
        jdbc.update("UPDATE agent_fetch_installation SET retained_for_rollback=FALSE,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",candidate.get("id"));
        audit(actor,"RELEASE_ROLLBACK","COMPLETED",operation,Map.of("requestId",request,"filesRemoved",false));
    });}
    public Map<String,Object> view(AgentActor actor){return tx.execute(status->{
        var current=jdbc.queryForList("SELECT * FROM agent_local_mcp WHERE owner_user_id=? AND server_key='fetch' FOR UPDATE",actor.userId());
        var reserved=unsettled(actor.userId());var usage=usage(actor.userId(),reserved);
        var physical=usage(actor.userId(),Set.of());
        var rows=jdbc.queryForList("SELECT installation_id AS installationId,state,revision,package_version AS packageVersion,transport,image_id AS imageId,writer_exit_verified AS writerExitVerified,writer_evidence_code AS writerEvidenceCode,retained_for_rollback AS retainedForRollback,updated_at AS updatedAt,(cleanup_expires_at<CURRENT_TIMESTAMP) AS cleanupExpired FROM agent_fetch_installation WHERE owner_user_id=? ORDER BY CASE WHEN state='NEEDS_REVIEW' AND writer_exit_verified=FALSE THEN 0 WHEN state='REMOVED' THEN 2 ELSE 1 END,id DESC LIMIT 40",actor.userId());
        for(var row:rows){row.put("writerExitVerified",flag(row.get("writerExitVerified")));row.put("retainedForRollback",flag(row.get("retainedForRollback")));row.put("current",!current.isEmpty()&&Set.of("INSTALLED","INSTALLING").contains(current.get(0).get("status"))&&Objects.equals(current.get(0).get("operation_id"),row.get("installationId")));if("CLEANING".equals(row.get("state"))&&flag(row.remove("cleanupExpired")))row.put("state","CLEANUP_REVIEW");else row.remove("cleanupExpired");}
        long held=reservedBytes(actor.userId());return Map.of("supported",true,"quotaBytes",quota,"storedBytes",physical.bytes(),"chargedBytes",Math.addExact(usage.bytes(),held),"reservedBytes",held,"fileCount",physical.files(),"items",rows,"sharedImageCleanupSupported",false,"writerReconciliationSupported",workers!=null);
    });}
    private Set<String> unsettled(long owner){return new HashSet<>(jdbc.queryForList("SELECT installation_id FROM agent_fetch_installation WHERE owner_user_id=? AND writer_exit_verified=FALSE AND state<>'REMOVED'",String.class,owner));}
    private long reservedBytes(long owner){Long value=jdbc.queryForObject("SELECT COALESCE(SUM(reserved_bytes),0) FROM agent_fetch_installation WHERE owner_user_id=? AND writer_exit_verified=FALSE AND state<>'REMOVED'",Long.class,owner);if(value==null||value<0)throw fail(503,"安装预留无法核对");return value;}
    private boolean hasPending(AgentActor actor,String operation){return jdbc.queryForObject("SELECT COUNT(*) FROM agent_mcp_execution WHERE owner_user_id=? AND installation_id=? AND state<>'REMOVED'",Long.class,actor.userId(),operation)>0;}
    private FetchInstallationStorage.Usage usage(long owner,Set<String> reserved){try{return storage.usage(owner,reserved);}catch(Exception error){throw fail(503,"MCP 存储用量无法核对 不继续安装或清理");}}
    private void requireNoPending(AgentActor actor,String operation){String filter=operation==null?"":" AND installation_id=?";Object[] args=operation==null?new Object[]{actor.userId()}:new Object[]{actor.userId(),operation};if(jdbc.queryForObject("SELECT COUNT(*) FROM agent_mcp_execution WHERE owner_user_id=? AND state<>'REMOVED'"+filter,Long.class,args)>0)throw fail(409,"仍有执行退出或清理待核对");}
    private Map<String,Object> registration(AgentActor actor){var rows=jdbc.queryForList("SELECT * FROM agent_local_mcp WHERE owner_user_id=? AND server_key='fetch' FOR UPDATE",actor.userId());if(rows.isEmpty())throw fail(409,"安装登记不存在");return rows.get(0);}
    private Map<String,Object> snapshot(AgentActor actor,String operation){if(operation==null||!uuid(operation))throw fail(400,"安装编号不合法");var rows=jdbc.queryForList("SELECT *,(cleanup_expires_at<CURRENT_TIMESTAMP) AS cleanup_expired FROM agent_fetch_installation WHERE owner_user_id=? AND installation_id=? FOR UPDATE",actor.userId(),operation);if(rows.isEmpty())throw fail(404,"本人版本记录不存在");return rows.get(0);}
    private boolean duplicate(AgentActor actor,String request,String fingerprint){if(request==null||!request.matches("[A-Za-z0-9_-]{8,64}"))throw fail(400,"请求编号不合法");var rows=jdbc.queryForList("SELECT request_sha256 FROM agent_fetch_lifecycle_command WHERE owner_user_id=? AND request_id=?",actor.userId(),request);if(rows.isEmpty())return false;if(!fingerprint.equals(rows.get(0).get("request_sha256")))throw fail(409,"请求编号已用于其他操作");return true;}
    private void command(AgentActor actor,String request,String operation,String action,String hash,String state){jdbc.update("INSERT INTO agent_fetch_lifecycle_command(owner_user_id,request_id,installation_id,action_name,request_sha256,status) VALUES(?,?,?,?,?,?)",actor.userId(),request,operation,action,hash,state);}
    private void audit(AgentActor actor,String action,String outcome,String operation,Map<String,Object> details){var versions=jdbc.queryForList("SELECT revision FROM agent_fetch_installation WHERE owner_user_id=? AND installation_id=?",Integer.class,actor.userId(),operation);int version=versions.isEmpty()?0:versions.get(0);jdbc.update("INSERT INTO agent_local_mcp_audit(owner_user_id,server_key,action_name,outcome,revision,operation_id,detail_json,created_at) VALUES(?,'fetch',?,?,?,?,?,CURRENT_TIMESTAMP)",actor.userId(),action,outcome,version,operation,write(details));}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("MCP_SNAPSHOT_ENCODING_FAILED");}}
    private Map<String,Object> read(Object value){try{return json.readValue(value instanceof byte[] bytes?new String(bytes,StandardCharsets.UTF_8):value.toString(),new TypeReference<LinkedHashMap<String,Object>>(){});}catch(Exception error){throw new IllegalStateException("MCP_SNAPSHOT_INVALID");}}
    private static String hash(String text){return FetchMcpRuntime.sha(text.getBytes(StandardCharsets.UTF_8));}
    private static boolean flag(Object value){return value instanceof Boolean b?b:value instanceof Number n&&n.intValue()!=0;}
    private static int number(Map<String,Object> row,String key){return ((Number)row.get(key)).intValue();}
    private static boolean uuid(String value){try{return UUID.fromString(value).toString().equals(value);}catch(Exception error){return false;}}
    private static ResponseStatusException fail(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
