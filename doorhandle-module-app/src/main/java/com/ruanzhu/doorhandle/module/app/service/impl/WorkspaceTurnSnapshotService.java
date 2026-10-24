package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Exact file/reference boundary, captured under the same owner lock and transaction as an assistant message. */
@Service
@ConditionalOnProperty(prefix="agentscope.context-store",name="enabled",havingValue="true")
public class WorkspaceTurnSnapshotService {
    private final JdbcTemplate jdbc;private final ObjectMapper json;
    public WorkspaceTurnSnapshotService(JdbcTemplate jdbc,ObjectMapper json){this.jdbc=jdbc;this.json=json;}
    @PostConstruct public void validate(){jdbc.queryForList("SELECT message_id,snapshot_json,snapshot_sha256 FROM agent_workspace_turn_snapshot WHERE 1=0");}
    public record BusinessRef(String kind,String resourceId){}
    public record Snapshot(List<String> files,List<BusinessRef> business){}

    public void lockOwner(long user){
        if(!TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("附件切点必须与消息同事务保存");
        jdbc.update("INSERT INTO agent_workspace_owner(user_id) VALUES(?) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id)",user);
        jdbc.queryForObject("SELECT user_id FROM agent_workspace_owner WHERE user_id=? FOR UPDATE",Long.class,user);
    }
    public void capture(TenantContext tenant,String session,long message){
        lockOwner(tenant.userId());assertMessage(tenant.userId(),session,message);
        var files=jdbc.queryForList("SELECT file_id FROM agent_workspace_file_ref WHERE user_id=? AND session_id=? ORDER BY id LIMIT 2001 FOR UPDATE",String.class,tenant.userId(),session);
        if(files.size()>2000)throw new IllegalStateException("会话附件数量超过切点快照上限，未保存不完整快照");
        var business=jdbc.queryForList("SELECT kind,resource_id FROM agent_workspace_business_ref WHERE user_id=? AND session_id=? ORDER BY id FOR UPDATE",tenant.userId(),session).stream()
                .map(row->new BusinessRef((String)row.get("kind"),(String)row.get("resource_id"))).toList();
        save(tenant.userId(),session,message,new Snapshot(files,business));
    }
    public boolean inherit(long user,String source,long message,String target){
        lockOwner(user);var snapshot=load(user,source,message);if(snapshot==null)return false;
        // A snapshot does not restore a reference that the user has since removed from the source conversation.
        for(String id:snapshot.files())jdbc.update("INSERT INTO agent_workspace_file_ref(user_id,session_id,file_id) SELECT user_id,?,file_id FROM agent_workspace_file_ref WHERE user_id=? AND session_id=? AND file_id=? ON DUPLICATE KEY UPDATE file_id=VALUES(file_id)",target,user,source,id);
        for(var ref:snapshot.business())jdbc.update("INSERT INTO agent_workspace_business_ref(user_id,session_id,kind,resource_id) SELECT user_id,?,kind,resource_id FROM agent_workspace_business_ref WHERE user_id=? AND session_id=? AND kind=? AND resource_id=? ON DUPLICATE KEY UPDATE resource_id=VALUES(resource_id)",target,user,source,ref.kind(),ref.resourceId());
        return true;
    }
    public void copy(long user,String source,long message,String target,long copied){
        lockOwner(user);assertMessage(user,source,message);assertMessage(user,target,copied);
        var snapshot=load(user,source,message);if(snapshot!=null)save(user,target,copied,snapshot);
    }
    private void assertMessage(long user,String session,long message){Long count=jdbc.queryForObject("SELECT COUNT(*) FROM chat_message m JOIN chat_session s ON s.session_id=m.session_id WHERE s.user_id=? AND m.session_id=? AND m.id=? AND m.role='assistant'",Long.class,user,session,message);if(count==null||count!=1)throw new SecurityException("附件切点消息不属于当前账号");}
    private Snapshot load(long user,String session,long message){
        var rows=jdbc.queryForList("SELECT snapshot_json,snapshot_sha256 FROM agent_workspace_turn_snapshot WHERE user_id=? AND session_id=? AND message_id=?",user,session,message);
        if(rows.isEmpty())return null;String body=(String)rows.get(0).get("snapshot_json");if(!hash(body).equals(rows.get(0).get("snapshot_sha256")))throw new IllegalStateException("附件切点快照损坏");
        try{var result=json.readValue(body,Snapshot.class);if(result.files()==null||result.files().size()>2000||result.business()==null||result.business().size()>20)throw new IllegalStateException("附件切点快照格式无效");return result;}catch(com.fasterxml.jackson.core.JsonProcessingException invalid){throw new IllegalStateException("附件切点快照不可读取");}
    }
    private void save(long user,String session,long message,Snapshot snapshot){
        String body;try{body=json.writeValueAsString(snapshot);}catch(com.fasterxml.jackson.core.JsonProcessingException invalid){throw new IllegalStateException("附件切点无法保存");}
        var prior=load(user,session,message);if(prior!=null){if(!prior.equals(snapshot))throw new IllegalStateException("附件切点已绑定不同内容");return;}
        String digest=hash(body);jdbc.update("INSERT INTO agent_workspace_turn_snapshot(user_id,session_id,message_id,snapshot_json,snapshot_sha256) VALUES(?,?,?,?,?)",user,session,message,body,digest);
        jdbc.update("INSERT INTO agent_workspace_audit(user_id,session_id,resource_id,action,content_sha256) VALUES(?,?,?,'TURN_FILES_CAPTURED',?)",user,session,Long.toString(message),digest);
    }
    private static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
}
