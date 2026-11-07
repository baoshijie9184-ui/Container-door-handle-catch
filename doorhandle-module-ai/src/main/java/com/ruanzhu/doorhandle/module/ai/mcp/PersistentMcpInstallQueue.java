package com.ruanzhu.doorhandle.module.ai.mcp;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;

/** 固定 Fetch 专用队列；调用方先锁注册行，在同一事务内登记和推进任务。 */
public final class PersistentMcpInstallQueue {
    public record Job(String operationId,AgentActor actor,String runtimeSha256){}
    private final JdbcTemplate jdbc;
    public PersistentMcpInstallQueue(JdbcTemplate jdbc){this.jdbc=jdbc;}
    public void schema(){jdbc.queryForList("SELECT resource_id AS operation_id,owner_user_id,mcp_owner_username AS owner_username,mcp_runtime_sha256 AS runtime_sha256,status,mcp_worker_token AS worker_token FROM workflow_instance WHERE kind='MCP_INSTALL_JOB' AND legacy_clock_json IS NULL AND (1=0) ");}
    public void enqueue(AgentActor actor,String operation,String runtimeSha256){
        if(runtimeSha256==null||!runtimeSha256.matches("[a-f0-9]{64}"))throw new IllegalStateException("INSTALL_RUNTIME_IDENTITY_INVALID");
        jdbc.update("""
            INSERT INTO workflow_instance(resource_id,owner_user_id,mcp_owner_username,mcp_runtime_sha256,
              status,created_at,updated_at,workflow_id,kind,idempotency_scope,resource_type,
              payload_version,payload_json,request_id,request_sha256,revision)
            VALUES(?,?,?,?,'QUEUED',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UUID(),
              'MCP_INSTALL_JOB','MCP_INSTALL_JOB','MCP_INSTALL_JOB',1,JSON_OBJECT('schemaVersion',1),?,SHA2(?,256),0)
            """,operation,actor.userId(),actor.username(),runtimeSha256,operation,operation);
    }
    public Optional<Job> next(){
        var rows=jdbc.queryForList("SELECT resource_id AS operation_id,owner_user_id,mcp_owner_username AS owner_username,mcp_runtime_sha256 AS runtime_sha256 FROM workflow_instance WHERE kind='MCP_INSTALL_JOB' AND legacy_clock_json IS NULL AND (status='QUEUED') ORDER BY id LIMIT 1");
        if(rows.isEmpty())return Optional.empty();var row=rows.get(0);
        return Optional.of(new Job((String)row.get("operation_id"),new AgentActor(((Number)row.get("owner_user_id")).longValue(),(String)row.get("owner_username"),AgentActor.Role.INSPECTOR),(String)row.get("runtime_sha256")));
    }
    public String claim(String operation){
        String token=UUID.randomUUID().toString();
        return jdbc.update("UPDATE workflow_instance SET status='RUNNING',mcp_worker_token=?,updated_at=UTC_TIMESTAMP(6) WHERE kind='MCP_INSTALL_JOB' AND legacy_clock_json IS NULL AND (resource_id=? AND status='QUEUED') ",token,operation)==1?token:null;
    }
    public boolean owns(String operation,String token){return token!=null&&jdbc.queryForObject("SELECT COUNT(*) FROM workflow_instance WHERE kind='MCP_INSTALL_JOB' AND legacy_clock_json IS NULL AND (resource_id=? AND status='RUNNING' AND mcp_worker_token=?) ",Integer.class,operation,token)==1;}
    /** 忙碌执行器的控制检查，不锁行或改写状态；只接受仍有效的本人执行令牌。 */
    public boolean executable(long owner,String operation,String token){
        if(token==null)return false;
        return Boolean.TRUE.equals(jdbc.query("SELECT COUNT(*) FROM workflow_instance j\n            JOIN agent_connector r ON r.owner_user_id=j.owner_user_id AND r.operation_id=j.resource_id AND r.server_key='fetch'\n            WHERE j.kind='MCP_INSTALL_JOB' AND j.legacy_clock_json IS NULL AND r.legacy_clock_json IS NULL AND (j.resource_id=? AND j.owner_user_id=? AND j.status='RUNNING' AND j.mcp_worker_token=?\n              AND r.status='INSTALLING' AND r.lease_expires_at>UTC_TIMESTAMP(6)) ",statement->{statement.setString(1,operation);statement.setLong(2,owner);statement.setString(3,token);statement.setQueryTimeout(2);},
                result->result.next()&&result.getInt(1)==1));
    }
    public void finish(String operation,String token,String outcome){
        jdbc.update("UPDATE workflow_instance SET status=?,updated_at=UTC_TIMESTAMP(6) WHERE kind='MCP_INSTALL_JOB' AND legacy_clock_json IS NULL AND (resource_id=? AND status='RUNNING' AND mcp_worker_token=?) ",outcome,operation,token);
    }
    public void revoke(String operation,String outcome){
        jdbc.update("UPDATE workflow_instance SET status=?,updated_at=UTC_TIMESTAMP(6) WHERE kind='MCP_INSTALL_JOB' AND legacy_clock_json IS NULL AND (resource_id=? AND status IN ('QUEUED','RUNNING')) ",outcome,operation);
    }
    public String phase(long owner,String operation){
        var rows=jdbc.queryForList("SELECT status FROM workflow_instance WHERE kind='MCP_INSTALL_JOB' AND (owner_user_id=? AND resource_id=?) ",owner,operation);
        return rows.isEmpty()?"LEGACY":(String)rows.get(0).get("status");
    }
}
