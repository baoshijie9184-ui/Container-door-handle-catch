package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;
import com.ruanzhu.doorhandle.framework.persistence.chat.JdbcMessageEvidenceStore;
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
    private final JdbcTemplate jdbc;private final ObjectMapper json;private final JdbcMessageEvidenceStore evidence;private final WorkspacePersistence workspace;
    public WorkspaceTurnSnapshotService(JdbcTemplate jdbc,ObjectMapper json){this.jdbc=jdbc;this.json=json;evidence=new JdbcMessageEvidenceStore(jdbc,json);workspace=new WorkspacePersistence(jdbc);}
    @PostConstruct public void validate(){evidence.validateSchema();workspace.validate();}
    public record BusinessRef(String kind,String resourceId){}
    public record Snapshot(List<String> files,List<BusinessRef> business){}

    public void lockOwner(long user){
        if(!TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("附件切点必须与消息同事务保存");
        JdbcOwnerLock.lock(jdbc, JdbcOwnerLock.Scope.WORKSPACE, user);
    }
    public void capture(TenantContext tenant,String session,long message){
        lockOwner(tenant.userId());assertMessage(tenant.userId(),session,message);
        var files=workspace.snapshotFiles(tenant.userId(),session);
        if(files.size()>2000)throw new IllegalStateException("会话附件数量超过切点快照上限，未保存不完整快照");
        var business=workspace.business(tenant.userId(),session,21,true,true).stream().map(row->new BusinessRef(row.kind(),row.resourceId())).toList();
        if(business.size()>20)throw new IllegalStateException("会话业务引用超过切点快照上限，未保存不完整快照");
        save(tenant.userId(),session,message,new Snapshot(files,business));
    }
    public boolean inherit(long user,String source,long message,String target){
        lockOwner(user);var snapshot=load(user,source,message);if(snapshot==null)return false;
        // A snapshot does not restore a reference that the user has since removed from the source conversation.
        for(String id:snapshot.files())workspace.inheritFile(user,source,target,id);
        for(var ref:snapshot.business())workspace.inheritBusiness(user,source,target,ref.kind(),ref.resourceId());
        return true;
    }
    public void copy(long user,String source,long message,String target,long copied){
        lockOwner(user);assertMessage(user,source,message);assertMessage(user,target,copied);
        var snapshot=load(user,source,message);if(snapshot!=null)save(user,target,copied,snapshot);
    }
    private void assertMessage(long user,String session,long message){Long count=jdbc.queryForObject("SELECT COUNT(*) FROM chat_message m JOIN chat_session s ON s.session_id=m.session_id WHERE s.user_id=? AND m.session_id=? AND m.id=? AND m.role='assistant'",Long.class,user,session,message);if(count==null||count!=1)throw new SecurityException("附件切点消息不属于当前账号");}
    private Snapshot load(long user,String session,long message){
        String body=evidence.loadSnapshot(user,session,message);if(body==null)return null;
        try{var result=json.readValue(body,Snapshot.class);if(result.files()==null||result.files().size()>2000||result.business()==null||result.business().size()>20)throw new IllegalStateException("附件切点快照格式无效");return result;}catch(com.fasterxml.jackson.core.JsonProcessingException invalid){throw new IllegalStateException("附件切点快照不可读取");}
    }
    private void save(long user,String session,long message,Snapshot snapshot){
        String body;try{body=json.writeValueAsString(snapshot);}catch(com.fasterxml.jackson.core.JsonProcessingException invalid){throw new IllegalStateException("附件切点无法保存");}
        evidence.saveSnapshot(user,session,message,body);
    }
    private static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
}
