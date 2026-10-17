package com.ruanzhu.doorhandle.module.ai.mcp;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;

/** 固定 Fetch 专用队列；调用方先锁注册行，在同一事务内登记和推进任务。 */
public final class PersistentMcpInstallQueue {
    public record Job(String operationId,AgentActor actor,String runtimeSha256){}
    private final JdbcTemplate jdbc;
    public PersistentMcpInstallQueue(JdbcTemplate jdbc){this.jdbc=jdbc;}
    public void schema(){jdbc.queryForList("SELECT operation_id,owner_user_id,owner_username,runtime_sha256,status,worker_token FROM agent_mcp_install_job WHERE 1=0");}
    public void enqueue(AgentActor actor,String operation,String runtimeSha256){
        if(runtimeSha256==null||!runtimeSha256.matches("[a-f0-9]{64}"))throw new IllegalStateException("INSTALL_RUNTIME_IDENTITY_INVALID");
        jdbc.update("INSERT INTO agent_mcp_install_job(operation_id,owner_user_id,owner_username,runtime_sha256,status,created_at,updated_at) VALUES(?,?,?,?,'QUEUED',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",operation,actor.userId(),actor.username(),runtimeSha256);
    }
    public Optional<Job> next(){
        var rows=jdbc.queryForList("SELECT operation_id,owner_user_id,owner_username,runtime_sha256 FROM agent_mcp_install_job WHERE status='QUEUED' ORDER BY id LIMIT 1");
        if(rows.isEmpty())return Optional.empty();var row=rows.get(0);
        return Optional.of(new Job((String)row.get("operation_id"),new AgentActor(((Number)row.get("owner_user_id")).longValue(),(String)row.get("owner_username"),AgentActor.Role.INSPECTOR),(String)row.get("runtime_sha256")));
    }
    public String claim(String operation){
        String token=UUID.randomUUID().toString();
        return jdbc.update("UPDATE agent_mcp_install_job SET status='RUNNING',worker_token=?,updated_at=CURRENT_TIMESTAMP WHERE operation_id=? AND status='QUEUED'",token,operation)==1?token:null;
    }
    public boolean owns(String operation,String token){return token!=null&&jdbc.queryForObject("SELECT COUNT(*) FROM agent_mcp_install_job WHERE operation_id=? AND status='RUNNING' AND worker_token=?",Integer.class,operation,token)==1;}
    /** 忙碌执行器的控制检查，不锁行或改写状态；只接受仍有效的本人执行令牌。 */
    public boolean executable(long owner,String operation,String token){
        if(token==null)return false;
        return Boolean.TRUE.equals(jdbc.query("""
            SELECT COUNT(*) FROM agent_mcp_install_job j
            JOIN agent_local_mcp r ON r.owner_user_id=j.owner_user_id AND r.operation_id=j.operation_id AND r.server_key='fetch'
            WHERE j.operation_id=? AND j.owner_user_id=? AND j.status='RUNNING' AND j.worker_token=?
              AND r.status='INSTALLING' AND r.lease_expires_at>CURRENT_TIMESTAMP
            """,statement->{statement.setString(1,operation);statement.setLong(2,owner);statement.setString(3,token);statement.setQueryTimeout(2);},
                result->result.next()&&result.getInt(1)==1));
    }
    public void finish(String operation,String token,String outcome){
        jdbc.update("UPDATE agent_mcp_install_job SET status=?,updated_at=CURRENT_TIMESTAMP WHERE operation_id=? AND status='RUNNING' AND worker_token=?",outcome,operation,token);
    }
    public void revoke(String operation,String outcome){
        jdbc.update("UPDATE agent_mcp_install_job SET status=?,updated_at=CURRENT_TIMESTAMP WHERE operation_id=? AND status IN ('QUEUED','RUNNING')",outcome,operation);
    }
    public String phase(long owner,String operation){
        var rows=jdbc.queryForList("SELECT status FROM agent_mcp_install_job WHERE owner_user_id=? AND operation_id=?",owner,operation);
        return rows.isEmpty()?"LEGACY":(String)rows.get(0).get("status");
    }
}
