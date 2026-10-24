package com.ruanzhu.doorhandle.module.ai.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Only execution metadata crosses the HTTP boundary. Unknown exits continue to hold capacity. */
public final class McpExecutionLedger {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final String transport;
    private final FetchImageRegistry images;
    public McpExecutionLedger(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json){
        this(jdbc,manager,json,"STREAMABLE_HTTP");
    }
    public McpExecutionLedger(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,String transport){
        this(jdbc,manager,json,transport,null);
    }
    public McpExecutionLedger(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,String transport,FetchImageRegistry images){
        if(!Set.of("STDIO","STREAMABLE_HTTP").contains(transport))throw new IllegalArgumentException("MCP_TRANSPORT_INVALID");this.transport=transport;
        this.jdbc=jdbc;this.json=json;this.images=images;this.tx=new TransactionTemplate(manager);
        tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);tx.setTimeout(10);
    }
    public void schema(){jdbc.queryForList("SELECT execution_id,transport FROM agent_mcp_execution WHERE 1=0");jdbc.queryForList("SELECT request_id FROM agent_mcp_execution_command WHERE 1=0");}
    public String reserve(AgentActor actor,String installation,String runtime,String pool,String purpose,String run,String call,boolean requireEnabled){
        if(!Set.of("CALL","PROBE","INSTALL_PROBE").contains(purpose)||!runtime.matches("[a-f0-9]{64}")||!pool.matches("[a-f0-9]{32}")||"INSTALL_PROBE".equals(purpose)&&requireEnabled)throw new IllegalArgumentException("MCP_EXECUTION_METADATA_INVALID");
        return tx.execute(status->{
            var registration=registration(actor.userId());
            String requiredStatus="INSTALL_PROBE".equals(purpose)?"INSTALLING":"INSTALLED";
            if(!installation.equals(registration.get("operation_id"))||!requiredStatus.equals(registration.get("status"))||requireEnabled&&!bool(registration.get("enabled")))throw fail(409,"MCP 安装或启用状态已变化");
            Long pending=jdbc.queryForObject("SELECT COUNT(*) FROM agent_mcp_execution WHERE owner_user_id=? AND state<>'REMOVED'",Long.class,actor.userId());
            if(pending!=null&&pending>=2)throw fail(409,"本人仍有执行或清理待核对 请先核对退出状态");
            String id=UUID.randomUUID().toString();
            if(images!=null&&images.available()){
                String image=null;
                if("STREAMABLE_HTTP".equals(transport)){
                    if("INSTALL_PROBE".equals(purpose))image=jdbc.queryForObject("SELECT image_id FROM agent_fetch_installation WHERE owner_user_id=? AND installation_id=?",String.class,actor.userId(),installation);
                    else try{var manifest=registration.get("manifest_json");image=json.readTree(manifest instanceof byte[] bytes?new String(bytes,StandardCharsets.UTF_8):manifest.toString()).path("image").asText();}catch(Exception error){throw fail(409,"镜像引用无法核对");}
                    if(image==null||!image.matches("sha256:[a-f0-9]{64}"))throw fail(409,"镜像引用无法核对");images.usable(image);
                }
                jdbc.update("INSERT INTO agent_mcp_execution(execution_id,owner_user_id,installation_id,runtime_sha256,pool_id,purpose,state,run_id,call_id,transport,image_id,lease_expires_at) VALUES(?,?,?,?,?,?,'OPENING',?,?,?,?,DATE_ADD(CURRENT_TIMESTAMP,INTERVAL 90 SECOND))",id,actor.userId(),installation,runtime,pool,purpose,run,call,transport,image);
            }else jdbc.update("INSERT INTO agent_mcp_execution(execution_id,owner_user_id,installation_id,runtime_sha256,pool_id,purpose,state,run_id,call_id,transport,lease_expires_at) VALUES(?,?,?,?,?,?,'OPENING',?,?,?,DATE_ADD(CURRENT_TIMESTAMP,INTERVAL 90 SECOND))",id,actor.userId(),installation,runtime,pool,purpose,run,call,transport);
            audit(actor,id,installation,0,"EXECUTION_OPEN","STARTED",Map.of("purpose",purpose,"exitVerified",false,"cleanupConfirmed",false));return id;
        });
    }
    public boolean started(AgentActor actor,String id){return tx.execute(status->{
        registration(actor.userId());var row=locked(actor,id);if(!"OPENING".equals(row.get("state")))return false;
        jdbc.update("UPDATE agent_mcp_execution SET state='RUNNING',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",row.get("id"));
        audit(actor,id,(String)row.get("installation_id"),revision(row)+1,"EXECUTION_OPEN","RUNNING",Map.of("exitVerified",false,"cleanupConfirmed",false));return true;
    });}
    public void observe(AgentActor actor,String id,Map<String,Object> evidence){tx.executeWithoutResult(status->{
        registration(actor.userId());var row=locked(actor,id);
        if("REMOVED".equals(row.get("state")))return;
        boolean exited=Boolean.TRUE.equals(evidence.get("exitVerified")),cleaned=exited&&Boolean.TRUE.equals(evidence.get("cleanupConfirmed"));
        // Exit is irreversible. A temporary later control outage cannot erase established evidence.
        exited=exited||bool(row.get("exit_verified"));cleaned=cleaned||bool(row.get("cleanup_confirmed"));
        String state=cleaned?"REMOVED":exited?"EXITED":"NEEDS_REVIEW";
        jdbc.update("UPDATE agent_mcp_execution SET state=?,exit_verified=?,cleanup_confirmed=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",state,exited,cleaned,row.get("id"));
        audit(actor,id,(String)row.get("installation_id"),revision(row)+1,"EXECUTION_EXIT",state,Map.of("exitVerified",exited,"cleanupConfirmed",cleaned));
    });}
    /** Starts one explicit reconciliation attempt. Duplicate request IDs never repeat network I/O. */
    public Optional<Map<String,Object>> claim(AgentActor actor,String id,int expected,String request){
        if(request==null||!request.matches("[A-Za-z0-9_-]{8,64}")||expected<0||!uuid(id))throw fail(400,"请核对执行编号、版本与请求编号");
        String hash=FetchMcpRuntime.sha((id+":"+expected+":STOP_AND_RECONCILE").getBytes(StandardCharsets.UTF_8));
        return tx.execute(status->{
            registration(actor.userId());
            var previous=jdbc.queryForList("SELECT request_sha256 FROM agent_mcp_execution_command WHERE owner_user_id=? AND request_id=?",actor.userId(),request);
            if(!previous.isEmpty()){if(!hash.equals(previous.get(0).get("request_sha256")))throw fail(409,"请求编号已用于其他操作");return Optional.empty();}
            var row=locked(actor,id);if(revision(row)!=expected)throw fail(409,"执行状态已变化 请刷新核对");
            if("REMOVED".equals(row.get("state")))throw fail(409,"此执行已确认清理 无需重复核对");
            if("STOPPING".equals(row.get("state"))&&!Boolean.TRUE.equals(row.get("lease_expired")))throw fail(409,"退出核对正在执行 请稍后刷新");
            jdbc.update("INSERT INTO agent_mcp_execution_command(owner_user_id,request_id,execution_id,request_sha256,status) VALUES(?,?,?,?,'STARTED')",actor.userId(),request,id,hash);
            jdbc.update("UPDATE agent_mcp_execution SET state='STOPPING',revision=revision+1,lease_expires_at=DATE_ADD(CURRENT_TIMESTAMP,INTERVAL 90 SECOND),updated_at=CURRENT_TIMESTAMP WHERE id=?",row.get("id"));
            audit(actor,id,(String)row.get("installation_id"),expected+1,"EXECUTION_RECONCILE","STARTED",Map.of("requestId",request));return Optional.of(row);
        });
    }
    public void finish(AgentActor actor,String id,String request,Map<String,Object> evidence){tx.executeWithoutResult(status->{
        observe(actor,id,evidence);
        jdbc.update("UPDATE agent_mcp_execution_command SET status=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND execution_id=? AND request_id=? AND status='STARTED'",Boolean.TRUE.equals(evidence.get("cleanupConfirmed"))?"COMPLETED":"NEEDS_REVIEW",actor.userId(),id,request);
    });}
    public Map<String,Object> view(AgentActor actor){
        var rows=jdbc.queryForList("SELECT execution_id AS executionId,installation_id AS installationId,purpose,transport,state,revision,exit_verified AS exitVerified,cleanup_confirmed AS cleanupConfirmed,created_at AS createdAt,updated_at AS updatedAt,(lease_expires_at<CURRENT_TIMESTAMP) AS leaseExpired FROM agent_mcp_execution WHERE owner_user_id=? ORDER BY CASE WHEN state='REMOVED' THEN 1 ELSE 0 END,id DESC LIMIT 30",actor.userId());
        Long pending=jdbc.queryForObject("SELECT COUNT(*) FROM agent_mcp_execution WHERE owner_user_id=? AND state<>'REMOVED'",Long.class,actor.userId());
        for(var row:rows){row.put("exitVerified",bool(row.get("exitVerified")));row.put("cleanupConfirmed",bool(row.get("cleanupConfirmed")));boolean expired=bool(row.remove("leaseExpired"));if(expired&&Set.of("OPENING","RUNNING","STOPPING").contains(row.get("state")))row.put("state","NEEDS_REVIEW");}
        return Map.of("supported",true,"transport",transport,"pendingCount",pending==null?0:pending,"items",rows);
    }
    public boolean hasPending(long owner){return jdbc.queryForObject("SELECT COUNT(*) FROM agent_mcp_execution WHERE owner_user_id=? AND state<>'REMOVED'",Long.class,owner)>0;}
    private Map<String,Object> registration(long owner){var rows=jdbc.queryForList("SELECT * FROM agent_local_mcp WHERE owner_user_id=? AND server_key='fetch' FOR UPDATE",owner);if(rows.isEmpty())throw fail(409,"MCP 安装登记不存在");return rows.get(0);}
    private Map<String,Object> locked(AgentActor actor,String id){var rows=jdbc.queryForList("SELECT *,(lease_expires_at<CURRENT_TIMESTAMP) AS lease_expired FROM agent_mcp_execution WHERE owner_user_id=? AND execution_id=? FOR UPDATE",actor.userId(),id);if(rows.isEmpty())throw fail(404,"执行不存在或无权访问");var row=rows.get(0);row.put("lease_expired",bool(row.get("lease_expired")));return row;}
    private void audit(AgentActor actor,String id,String installation,int version,String action,String outcome,Map<String,Object> detail){
        var data=new LinkedHashMap<String,Object>(detail);data.put("executionId",id);
        try{jdbc.update("INSERT INTO agent_local_mcp_audit(owner_user_id,server_key,action_name,outcome,revision,operation_id,detail_json,created_at) VALUES(?,'fetch',?,?,?,?,?,CURRENT_TIMESTAMP)",actor.userId(),action,outcome,version,installation,json.writeValueAsString(data));}
        catch(com.fasterxml.jackson.core.JsonProcessingException error){throw new IllegalStateException("MCP_EXECUTION_AUDIT_UNAVAILABLE",error);}
    }
    private static boolean bool(Object value){return value instanceof Boolean b?b:value instanceof Number n&&n.intValue()!=0;}
    private static int revision(Map<String,Object> row){return ((Number)row.get("revision")).intValue();}
    private static boolean uuid(String value){try{return value!=null&&UUID.fromString(value).toString().equals(value);}catch(IllegalArgumentException error){return false;}}
    private static ResponseStatusException fail(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
