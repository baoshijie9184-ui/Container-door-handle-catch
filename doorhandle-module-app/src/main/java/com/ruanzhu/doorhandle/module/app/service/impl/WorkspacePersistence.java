package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.WorkbenchSessionApi;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import com.ruanzhu.doorhandle.framework.persistence.content.ContentKind;
import com.ruanzhu.doorhandle.framework.persistence.content.JdbcContentStore;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;

/** Typed workspace storage; current session authorization remains with the domain service. */
final class WorkspacePersistence {
    static final String AUDIT_KIND="WORKSPACE";
    private static final DateTimeFormatter SOURCE_TIME=DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS");
    private static final String FILE_COLUMNS="a.asset_id AS file_id,r.filename,r.media_type,r.byte_length,r.content_sha256,r.manifest_json";
    private static final String FILES="content_asset a JOIN content_revision r ON r.asset_id=a.asset_id AND r.asset_kind=a.asset_kind AND r.version=a.current_version";
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcContentStore content;
    private final JdbcWorkflowStore workflows;
    private final JdbcAuditStore audits;

    record FileManifestV1(String folder,String createdAtSource,String sourceUtcOffset) { }
    record AuditV1(String createdAtSource,String sourceUtcOffset) { }
    record WorkspaceMutationV1(String signature) {
        WorkspaceMutationV1 { if(signature==null||!signature.matches("[a-fA-F0-9]{64}"))throw new IllegalArgumentException("Invalid workspace mutation signature"); }
    }
    record BusinessReference(String kind,String resourceId) { }

    WorkspacePersistence(JdbcTemplate jdbc) {
        this.jdbc=jdbc;
        json=new ObjectMapper().setSerializationInclusion(JsonInclude.Include.ALWAYS)
                .enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES);
        content=new JdbcContentStore(jdbc);
        var mutation=new WorkflowProtocol<>(WorkflowKind.WORKSPACE_MUTATION,1,WorkspaceMutationV1.class,
                Set.of("COMPLETED"),Set.of("COMPLETED"),Map.of(),value->{});
        workflows=new JdbcWorkflowStore(jdbc,json,WorkflowProtocols.defaults().with(mutation));
        audits=new JdbcAuditStore(jdbc,json,Map.of(AUDIT_KIND,AuditV1.class));
    }
    void validate() {
        jdbc.queryForList("SELECT asset_id,asset_kind,owner_user_id,current_version FROM content_asset WHERE 1=0");
        jdbc.queryForList("SELECT manifest_json,request_id,object_key FROM content_revision WHERE 1=0");
        jdbc.queryForList("SELECT workspace_file_id,workspace_business_type,target_id FROM content_link WHERE 1=0");
        workflows.validateSchema();audits.validateSchema();
    }
    LocalDateTime now(){return jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)",LocalDateTime.class);}
    List<WorkbenchSessionApi.File> files(long owner,String session) {
        return jdbc.queryForList("SELECT "+FILE_COLUMNS+" FROM "+FILES+" JOIN content_link l ON l.workspace_file_id=a.asset_id AND l.owner_user_id=a.owner_user_id WHERE a.asset_kind='WORKSPACE_FILE' AND l.link_kind='WORKSPACE_FILE' AND l.state='ACTIVE' AND l.owner_user_id=? AND l.session_id=? ORDER BY a.id DESC LIMIT 200",owner,session).stream().map(this::file).toList();
    }
    Optional<WorkbenchSessionApi.File> file(long owner,String session,String id) {
        var rows=jdbc.queryForList("SELECT "+FILE_COLUMNS+" FROM "+FILES+" JOIN content_link l ON l.workspace_file_id=a.asset_id AND l.owner_user_id=a.owner_user_id WHERE a.asset_kind='WORKSPACE_FILE' AND l.link_kind='WORKSPACE_FILE' AND l.state='ACTIVE' AND l.owner_user_id=? AND l.session_id=? AND a.asset_id=?",owner,session,id);
        return rows.isEmpty()?Optional.empty():Optional.of(file(rows.get(0)));
    }
    Optional<WorkbenchSessionApi.File> byRequest(long owner,String request) {
        JdbcTransactions.requireActive(jdbc);
        var rows=jdbc.queryForList("SELECT "+FILE_COLUMNS+" FROM "+FILES+" WHERE a.asset_kind='WORKSPACE_FILE' AND r.owner_user_id=? AND r.request_id=? FOR SHARE",owner,request);
        return rows.isEmpty()?Optional.empty():Optional.of(file(rows.get(0)));
    }
    private WorkbenchSessionApi.File file(Map<String,Object> row) {
        var manifest=read((String)row.get("manifest_json"),FileManifestV1.class);
        if(manifest.folder()==null||manifest.createdAtSource()==null||manifest.sourceUtcOffset()==null)throw corrupt();
        return new WorkbenchSessionApi.File((String)row.get("file_id"),(String)row.get("filename"),(String)row.get("media_type"),((Number)row.get("byte_length")).longValue(),(String)row.get("content_sha256"),manifest.folder());
    }
    long usedBytes(long owner){return jdbc.queryForObject("SELECT COALESCE(SUM(r.byte_length),0) FROM content_revision r JOIN content_asset a ON a.asset_id=r.asset_id AND a.asset_kind=r.asset_kind WHERE a.asset_kind='WORKSPACE_FILE' AND a.owner_user_id=?",Long.class,owner);}
    boolean hasFileReference(long owner,String session,String file){return jdbc.queryForObject("SELECT COUNT(*) FROM content_link WHERE link_kind='WORKSPACE_FILE' AND state='ACTIVE' AND owner_user_id=? AND session_id=? AND workspace_file_id=?",Integer.class,owner,session,file)==1;}
    void createFile(long owner,String session,String request,WorkbenchSessionApi.File file) {
        JdbcTransactions.requireActive(jdbc);var time=now();
        content.prepare(new JdbcContentStore.AssetDraft(file.id(),ContentKind.WORKSPACE_FILE,owner,file.name(),file.name(),"PRIVATE",null,null,time));
        jdbc.update("INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,filename,content_sha256,byte_length,media_type,object_key,manifest_json,request_id,created_at) VALUES(?,'WORKSPACE_FILE',1,?,?,?,?,?,?,?,?,?)",file.id(),owner,file.name(),file.sha256(),file.bytes(),file.contentType(),"users/"+owner+"/"+file.id()+".bin",write(new FileManifestV1(file.folder(),SOURCE_TIME.format(time),"+00:00")),request,time);
        if(jdbc.update("UPDATE content_asset SET current_version=1,lifecycle='ACTIVE',updated_at=? WHERE asset_kind='WORKSPACE_FILE' AND asset_id=? AND current_version IS NULL",time,file.id())!=1)throw corrupt();
        linkFile(owner,session,file.id());
    }
    void linkFile(long owner,String session,String file) {
        JdbcTransactions.requireActive(jdbc);lockSession(owner,session);
        // Historical orphan links may exist, but every new link requires an extant, same-owner asset.
        var asset=jdbc.queryForList("SELECT a.asset_id FROM "+FILES+" WHERE a.asset_kind='WORKSPACE_FILE' AND a.owner_user_id=? AND a.asset_id=? AND a.lifecycle='ACTIVE' FOR SHARE",owner,file);
        if(asset.size()!=1)throw new SecurityException("文件不存在或不属于当前账号");
        jdbc.update("INSERT INTO content_link(link_kind,owner_user_id,session_id,target_type,target_id,created_at) VALUES('WORKSPACE_FILE',?,?,'WORKSPACE_FILE',?,UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE target_id=VALUES(target_id)",owner,session,file);
    }
    void unlinkFile(long owner,String session,String file){JdbcTransactions.requireActive(jdbc);lockSession(owner,session);jdbc.update("DELETE FROM content_link WHERE link_kind='WORKSPACE_FILE' AND owner_user_id=? AND session_id=? AND workspace_file_id=?",owner,session,file);}
    List<String> snapshotFiles(long owner,String session){JdbcTransactions.requireActive(jdbc);return jdbc.queryForList("SELECT workspace_file_id FROM content_link WHERE link_kind='WORKSPACE_FILE' AND state='ACTIVE' AND owner_user_id=? AND session_id=? ORDER BY id LIMIT 2001 FOR UPDATE",String.class,owner,session);}
    List<BusinessReference> business(long owner,String session,int limit,boolean oldest,boolean lock) {
        if(limit<1||limit>2001)throw new IllegalArgumentException("Invalid workspace reference limit");
        if(lock)JdbcTransactions.requireActive(jdbc);
        return jdbc.queryForList("SELECT target_type,target_id FROM content_link WHERE link_kind='WORKSPACE_BUSINESS' AND state='ACTIVE' AND owner_user_id=? AND session_id=? ORDER BY id "+(oldest?"ASC":"DESC")+" LIMIT ?"+(lock?" FOR UPDATE":""),owner,session,limit).stream().map(row->new BusinessReference((String)row.get("target_type"),(String)row.get("target_id"))).toList();
    }
    boolean hasBusiness(long owner,String session,String kind,String resource){return jdbc.queryForObject("SELECT COUNT(*) FROM content_link WHERE link_kind='WORKSPACE_BUSINESS' AND state='ACTIVE' AND owner_user_id=? AND session_id=? AND workspace_business_type=? AND target_id=?",Integer.class,owner,session,kind,resource)==1;}
    long businessCount(long owner,String session){return jdbc.queryForObject("SELECT COUNT(*) FROM content_link WHERE link_kind='WORKSPACE_BUSINESS' AND state='ACTIVE' AND owner_user_id=? AND session_id=?",Long.class,owner,session);}
    void linkBusiness(long owner,String session,String kind,String resource){JdbcTransactions.requireActive(jdbc);lockSession(owner,session);jdbc.update("INSERT INTO content_link(link_kind,owner_user_id,session_id,target_type,target_id,created_at) VALUES('WORKSPACE_BUSINESS',?,?,?,?,UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE target_id=VALUES(target_id)",owner,session,kind,resource);}
    private void lockSession(long owner,String session){if(jdbc.queryForList("SELECT session_id FROM chat_session WHERE user_id=? AND BINARY session_id=BINARY ? FOR SHARE",owner,session).size()!=1)throw new SecurityException("会话不存在或不属于当前账号");}
    void inheritFile(long owner,String source,String target,String file) {if(hasFileReference(owner,source,file))linkFile(owner,target,file);}
    void inheritBusiness(long owner,String source,String target,String kind,String resource) {if(hasBusiness(owner,source,kind,resource))linkBusiness(owner,target,kind,resource);}
    void inheritBefore(long owner,String source,String target,LocalDateTime utcCutoff) {
        JdbcTransactions.requireActive(jdbc);
        // Never reattach a deleted source reference. Exact snapshots are preferred over this legacy cutoff.
        for(String file:jdbc.queryForList("SELECT workspace_file_id FROM content_link WHERE link_kind='WORKSPACE_FILE' AND state='ACTIVE' AND owner_user_id=? AND session_id=? AND created_at<? ORDER BY id FOR UPDATE",String.class,owner,source,utcCutoff))inheritFile(owner,source,target,file);
        for(var row:jdbc.queryForList("SELECT target_type,target_id FROM content_link WHERE link_kind='WORKSPACE_BUSINESS' AND state='ACTIVE' AND owner_user_id=? AND session_id=? AND created_at<? ORDER BY id FOR UPDATE",owner,source,utcCutoff))inheritBusiness(owner,source,target,(String)row.get("target_type"),(String)row.get("target_id"));
    }
    boolean hasMutation(long owner,String request,String signature) {
        var old=workflows.findByRequestLocked(WorkflowKind.WORKSPACE_MUTATION,JdbcWorkflowStore.ownerScope(owner),request);
        if(old.isEmpty())return false;
        var receipt=old.get();if(receipt.ownerUserId()!=owner||!signature.equals(receipt.requestSha256())||!signature.equals(workflows.payload(receipt,WorkspaceMutationV1.class).signature()))throw conflict();return true;
    }
    void mutation(long owner,String request,String signature){workflows.create(new WorkflowDraft(UUID.randomUUID().toString(),WorkflowKind.WORKSPACE_MUTATION,JdbcWorkflowStore.ownerScope(owner),request,signature,owner,owner,null,"WORKSPACE_MUTATION",null,null,null,null,"COMPLETED",null,1,new WorkspaceMutationV1(signature)));}
    Optional<WorkflowPayloads.WorkspaceForkV1> fork(long owner,String request) {
        return workflows.findByRequestLocked(WorkflowKind.WORKSPACE_FORK,JdbcWorkflowStore.ownerScope(owner),request).map(record->{if(record.ownerUserId()!=owner)throw corrupt();return workflows.payload(record,WorkflowPayloads.WorkspaceForkV1.class);});
    }
    void fork(long owner,String request,String signature,String source,long through,String child){workflows.create(new WorkflowDraft(UUID.randomUUID().toString(),WorkflowKind.WORKSPACE_FORK,JdbcWorkflowStore.ownerScope(owner),request,signature,owner,owner,null,"SESSION",child,null,null,null,"COMPLETED",null,1,new WorkflowPayloads.WorkspaceForkV1(source,through,child)));}
    void audit(long owner,String session,String resource,String action,String digest) {
        LocalDateTime time=now();audits.append(new AuditEvent(AUDIT_KIND,owner,owner,"WORKSPACE",resource,session,null,null,null,action,null,digest.toLowerCase(Locale.ROOT),time,1,new AuditV1(SOURCE_TIME.format(time),"+00:00")));
    }
    boolean legacyBoundary(long owner,String session){return jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='WORKSPACE' AND owner_user_id=? AND session_id=? AND action COLLATE utf8mb4_0900_ai_ci='FORK_LEGACY_FILE_BOUNDARY'",Long.class,owner,session)>0;}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(JsonProcessingException invalid){throw new IllegalArgumentException("Invalid workspace metadata",invalid);}}
    private <T>T read(String value,Class<T> type){try{return json.readValue(value,type);}catch(JsonProcessingException invalid){throw new IllegalStateException("Unreadable workspace metadata",invalid);}}
    private static IllegalStateException corrupt(){return new IllegalStateException("Workspace persistence identity is inconsistent");}
    private static org.springframework.web.server.ResponseStatusException conflict(){return new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"请求编号已使用");}
}
