package com.ruanzhu.doorhandle.module.ai.mcp;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.springframework.jdbc.core.JdbcTemplate;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Native installers require both JVM completion and an independent supervisor tree receipt. */
public final class McpInstallWorkerEvidence {
    public record Proof(boolean verified,String code){}
    public record Capture(String node,String runtime,long pid,String started,Map<String,Object> container){}
    private final JdbcTemplate jdbc;private final FetchMcpRuntime runtime;private final String configuredNode;
    public McpInstallWorkerEvidence(JdbcTemplate jdbc,FetchMcpRuntime runtime,String configuredNode){
        if(!"STREAMABLE_HTTP".equals(runtime.transport())&&!runtime.nativeInstallSupervised())throw new IllegalArgumentException("MCP_INSTALL_PROOF_REQUIRES_SUPERVISOR");
        this.jdbc=jdbc;this.runtime=runtime;this.configuredNode=configuredNode;
    }
    public void schema(){jdbc.queryForList("SELECT controller_pid,controller_started,node_sha256,writer_transport,native_pool_id FROM agent_mcp_install_worker WHERE 1=0");node();}
    public Capture capture(Path directory){
        var current=ProcessHandle.current();String started=current.info().startInstant().orElseThrow(()->new IllegalStateException("MCP_CONTROLLER_IDENTITY_UNAVAILABLE")).toString();
        return new Capture(node(),runtime.installationIdentity(),current.pid(),started,runtime.installationController(directory));
    }
    public void dispatched(AgentActor actor,String operation,Capture capture){
        jdbc.update("INSERT INTO agent_mcp_install_worker(owner_user_id,installation_id,node_sha256,runtime_sha256,controller_pid,controller_started,container_id,container_started,controller_pool_id,writer_transport,native_pool_id,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,'RUNNING')",actor.userId(),operation,capture.node(),capture.runtime(),capture.pid(),capture.started(),capture.container().get("id"),capture.container().get("started"),capture.container().get("pool"),runtime.transport(),capture.container().get("nativePool"));
    }
    public void returned(AgentActor actor,String operation){
        var current=ProcessHandle.current();var started=current.info().startInstant();if(started.isEmpty())return;
        jdbc.update("UPDATE agent_mcp_install_worker SET state='RETURNED',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND installation_id=? AND controller_pid=? AND controller_started=? AND node_sha256=?",actor.userId(),operation,current.pid(),started.get().toString(),node());
    }
    public Proof proof(AgentActor actor,String operation,Path directory){
        var rows=jdbc.queryForList("SELECT * FROM agent_mcp_install_worker WHERE owner_user_id=? AND installation_id=?",actor.userId(),operation);
        if(rows.isEmpty())return new Proof(false,"NO_CONTROLLER_EVIDENCE");var row=rows.get(0);
        if("STDIO".equals(row.get("writer_transport"))){
            if(!runtime.nativeInstallSupervised()||!(row.get("native_pool_id") instanceof String pool)||!pool.matches("[a-f0-9]{32}"))return new Proof(false,"NATIVE_INSTALLER_UNVERIFIED");
            boolean javaStopped="RETURNED".equals(row.get("state"));
            if(!javaStopped&&Objects.equals(row.get("node_sha256"),node())){
                var controller=ProcessHandle.of(((Number)row.get("controller_pid")).longValue());
                javaStopped=controller.isEmpty()||!controller.get().isAlive()||controller.get().info().startInstant().map(start->!start.toString().equals(row.get("controller_started"))).orElse(false);
            }
            if(!javaStopped)return new Proof(false,"CONTROLLER_STILL_ALIVE");
            boolean stopped=runtime.nativeInstallerStopped(directory,pool);
            return new Proof(stopped,stopped?"NATIVE_INSTALL_TREE_STOPPED":"NATIVE_INSTALLER_UNVERIFIED");
        }
        if("RETURNED".equals(row.get("state")))return new Proof(true,"WRITER_RETURNED");
        if(!Objects.equals(row.get("node_sha256"),node()))return remote(row,directory);
        var controller=ProcessHandle.of(((Number)row.get("controller_pid")).longValue());
        if(controller.isEmpty()||!controller.get().isAlive())return new Proof(true,"CONTROLLER_EXIT_CONFIRMED");
        var started=controller.get().info().startInstant();if(started.isEmpty())return remote(row,directory);
        return started.get().toString().equals(row.get("controller_started"))?new Proof(false,"CONTROLLER_STILL_ALIVE"):new Proof(true,"CONTROLLER_GENERATION_REPLACED");
    }
    private Proof remote(Map<String,Object> row,Path directory){
        if(row.get("container_id")==null||row.get("container_started")==null||row.get("controller_pool_id")==null)return new Proof(false,"CONTROLLER_NAMESPACE_CHANGED");
        boolean stopped=runtime.installationControllerStopped(directory,(String)row.get("container_id"),(String)row.get("container_started"),(String)row.get("controller_pool_id"));
        return new Proof(stopped,stopped?"CONTROLLER_CONTAINER_EXITED":"CONTROLLER_CONTAINER_UNVERIFIED");
    }
    private String node(){
        try{
            String identity;
            if(System.getProperty("os.name","").toLowerCase(Locale.ROOT).contains("linux"))identity="linux:"+Files.readString(Path.of("/proc/sys/kernel/random/boot_id")).trim()+":"+Files.readSymbolicLink(Path.of("/proc/self/ns/pid"));
            else{if(configuredNode==null||!configuredNode.matches("[A-Za-z0-9_.:-]{16,160}"))throw new IllegalStateException("MCP_INSTALL_PROCESS_NODE_REQUIRED");identity="configured:"+configuredNode;}
            return FetchMcpRuntime.sha(identity.getBytes(StandardCharsets.UTF_8));
        }catch(java.io.IOException error){throw new IllegalStateException("MCP_CONTROLLER_NAMESPACE_UNAVAILABLE");}
    }
}
