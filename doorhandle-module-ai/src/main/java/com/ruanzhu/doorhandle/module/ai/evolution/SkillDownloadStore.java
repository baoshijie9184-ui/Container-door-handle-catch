package com.ruanzhu.doorhandle.module.ai.evolution;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import com.ruanzhu.doorhandle.framework.persistence.content.ContentKind;
import com.ruanzhu.doorhandle.framework.persistence.content.JdbcContentStore;
import com.ruanzhu.doorhandle.framework.persistence.workflow.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;

/** Registered download/cleanup protocols. Package content and mutable execution facts have separate owners. */
final class SkillDownloadStore {
    record LeaseEvidenceV1(String workerInstance,Long processPid,String processStartedAt,LocalDateTime createdAt,LocalDateTime updatedAt) { }
    record DownloadV1(String sourceUrl,String targetRole,String targetSkillId,Integer expectedSkillRevision,String skillId,LeaseEvidenceV1 lease) {
        DownloadV1 withLease(LeaseEvidenceV1 value){return new DownloadV1(sourceUrl,targetRole,targetSkillId,expectedSkillRevision,skillId,value);}
        DownloadV1 withSkill(String id){return new DownloadV1(sourceUrl,targetRole,targetSkillId,expectedSkillRevision,id,lease);}
    }
    record CleanupV1(String downloadId,long removedBytes,int removedFiles) { }
    record DownloadEventV1(String status) { }
    record Claim(String token,long fence,String worker) { }
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final JdbcWorkflowStore workflows;
    private final JdbcAuditStore audits;
    private final JdbcContentStore content;
    private static final WorkflowProtocol<DownloadV1> DOWNLOAD=new WorkflowProtocol<>(WorkflowKind.SKILL_DOWNLOAD,1,DownloadV1.class,
            Set.of("DOWNLOADING"),Set.of("PURGED"),Map.of(
            "DOWNLOADING",Set.of("DOWNLOADING","DOWNLOADED","ERROR","NEEDS_REVIEW"),
            "DOWNLOADED",Set.of("DRAFT_CREATED","NO_CHANGE","ERROR","NEEDS_REVIEW"),
            "DRAFT_CREATED",Set.of("PURGING"),"NO_CHANGE",Set.of("PURGING"),"ERROR",Set.of("PURGING"),
            "NEEDS_REVIEW",Set.of("NEEDS_REVIEW","ERROR"),"PURGING",Set.of("PURGED","CLEANUP_ERROR"),"CLEANUP_ERROR",Set.of("PURGING")),
            SkillDownloadStore::validate);
    private static final WorkflowProtocol<CleanupV1> CLEANUP=new WorkflowProtocol<>(WorkflowKind.SKILL_STORAGE_COMMAND,1,CleanupV1.class,
            Set.of("STARTED"),Set.of("COMPLETED","ERROR"),Map.of("STARTED",Set.of("COMPLETED","ERROR")),value->{
                if(value.downloadId()==null||!value.downloadId().matches("download-[a-f0-9-]{36}")||value.removedBytes()<0||value.removedFiles()<0)
                    throw new IllegalArgumentException("Invalid skill cleanup payload");
            });
    private static final WorkflowProtocol<SkillContentStore.ImportReceiptV1> IMPORT=new WorkflowProtocol<>(WorkflowKind.SKILL_IMPORT_COMMAND,1,
            SkillContentStore.ImportReceiptV1.class,Set.of("COMPLETED"),Set.of("COMPLETED"),Map.of(),value->{
                if(value.importId()==null||value.importId().isBlank()||value.importId().length()>128||value.packageSha256()==null||!value.packageSha256().matches("[a-f0-9]{64}"))
                    throw new IllegalArgumentException("Invalid historical skill import receipt");
            });
    SkillDownloadStore(JdbcTemplate jdbc,ObjectMapper json) {
        this.jdbc=jdbc;this.json=json.copy().findAndRegisterModules().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
        this.workflows=new JdbcWorkflowStore(jdbc,this.json,WorkflowProtocols.defaults().with(DOWNLOAD).with(CLEANUP).with(IMPORT));
        this.audits=new JdbcAuditStore(jdbc,this.json,Map.of("SKILL_DOWNLOAD_EVENT",DownloadEventV1.class));
        this.content=new JdbcContentStore(jdbc);
    }
    void schema(){workflows.validateSchema();audits.validateSchema();jdbc.queryForList("SELECT execution_state,reserved_bytes,exit_verified,execution_deadline FROM workflow_instance WHERE kind='SKILL_DOWNLOAD' AND 1=0");}
    private static void validate(DownloadV1 value) {
        if(value.sourceUrl()==null||value.sourceUrl().isBlank()||value.sourceUrl().length()>1000||!Set.of("INSPECTOR","SUPERVISOR").contains(value.targetRole())
                ||(value.targetSkillId()==null)!=(value.expectedSkillRevision()==null)||value.expectedSkillRevision()!=null&&value.expectedSkillRevision()<1)
            throw new IllegalArgumentException("Invalid skill download payload");
        if(value.lease()!=null&&(value.lease().createdAt()==null||value.lease().updatedAt()==null||value.lease().processPid()!=null&&value.lease().processPid()<=0))
            throw new IllegalArgumentException("Invalid skill process evidence");
    }
    private WorkflowRecord row(long owner,String id,boolean lock) {
        var record=(lock?workflows.findLocked(WorkflowKind.SKILL_DOWNLOAD,id):workflows.find(WorkflowKind.SKILL_DOWNLOAD,id)).orElseThrow(()->conflict("下载记录不存在或无权限"));
        if(record.ownerUserId()!=owner)throw conflict("下载记录不存在或无权限");
        if(lock)LegacyWorkflowClocks.requireResolved(record);return record;
    }
    private DownloadV1 payload(WorkflowRecord row){return workflows.payload(row,DownloadV1.class);}
    private Map<String,Object> view(WorkflowRecord row) {
        var p=payload(row);var result=new LinkedHashMap<String,Object>();
        result.put("download_id",row.workflowId());result.put("owner_user_id",row.ownerUserId());result.put("request_id",row.requestId());result.put("request_sha256",row.requestSha256());
        result.put("source_url",p.sourceUrl());result.put("target_role",p.targetRole());result.put("target_skill_id",p.targetSkillId());result.put("expected_skill_revision",p.expectedSkillRevision());
        result.put("status",row.status());result.put("skill_id",p.skillId());result.put("error_code",row.errorCode());result.put("created_at",row.createdAt());result.put("updated_at",row.updatedAt());
        if(row.legacyClockUnresolved()){result.put("clockStatus",row.legacyClockEvidence().clockStatus());result.put("sourceWallTimes",row.legacyClockEvidence().sourceWallTimes());}return result;
    }
    Map<String,Object> download(long owner,String id,boolean lock){return view(row(owner,id,lock));}
    List<Map<String,Object>> lookup(long owner,String id,boolean lock){return (lock?workflows.findLocked(WorkflowKind.SKILL_DOWNLOAD,id):workflows.find(WorkflowKind.SKILL_DOWNLOAD,id)).filter(value->value.ownerUserId()==owner).map(value->List.of(view(value))).orElseGet(List::of);}
    List<Map<String,Object>> requested(long owner,String request) {
        return workflows.findByRequest(WorkflowKind.SKILL_DOWNLOAD,"OWNER:"+owner,request).map(value->List.of(view(value))).orElseGet(List::of);
    }
    List<Map<String,Object>> list(long owner){return workflows.list(WorkflowKind.SKILL_DOWNLOAD,owner,null,null,Set.of(),false,50,false).stream().map(this::view).toList();}
    void create(long owner,String id,String request,String digest,String url,String role,String target,Integer revision) {
        workflows.create(new WorkflowDraft(id,WorkflowKind.SKILL_DOWNLOAD,"OWNER:"+owner,request,digest,owner,owner,null,
                "SKILL_DOWNLOAD",id,1L,null,null,"DOWNLOADING",null,1,new DownloadV1(url,role,target,revision,null,null)));
    }
    void packageReady(long owner,String id,String manifest,String digest) {
        var before=row(owner,id,true);if(!"DOWNLOADING".equals(before.status())||!"SEALED".equals(execution(before).get("execution_state")))throw conflict("下载任务已变化");
        content.prepare(new JdbcContentStore.AssetDraft(id,ContentKind.SKILL_IMPORT,owner,"链接技能包",null,"PRIVATE",null,null,workflows.now()));
        jdbc.update("INSERT INTO content_revision(asset_id,asset_kind,version,owner_user_id,creator_user_id,source_type,manifest_json,manifest_sha256,stored_content_sha256,created_at) VALUES(?,'SKILL_IMPORT',1,?,?,'LINK',?,?,?,UTC_TIMESTAMP(6))",id,owner,owner,manifest,digest,sha(manifest));
        jdbc.update("UPDATE content_asset SET current_version=1,lifecycle='ACTIVE' WHERE asset_kind='SKILL_IMPORT' AND asset_id=?",id);
        workflows.transition(before,"DOWNLOADED",payload(before),null,null,null);
    }
    List<Map<String,Object>> packageEvidence(long owner,String id) {
        return jdbc.queryForList("SELECT w.status,r.manifest_json,r.manifest_sha256 FROM workflow_instance w JOIN content_revision r ON r.asset_id=w.workflow_id AND r.asset_kind='SKILL_IMPORT' AND r.version=1 AND r.owner_user_id=w.owner_user_id WHERE w.kind='SKILL_DOWNLOAD' AND w.workflow_id=? AND w.owner_user_id=?",id,owner);
    }
    void noChange(long owner,String id,String skill){var before=row(owner,id,true);workflows.transition(before,"NO_CHANGE",payload(before).withSkill(skill),null,null,null);}
    void draftCreated(long owner,String id,String skill) {
        var before=row(owner,id,true);if("NO_CHANGE".equals(before.status())){if(!Objects.equals(skill,payload(before).skillId()))throw conflict("下载结果技能已变化");return;}
        workflows.transition(before,"DRAFT_CREATED",payload(before).withSkill(skill),null,null,null);
    }
    Map<String,Long> held(long owner) {
        var result=new LinkedHashMap<String,Long>();
        for(var row:jdbc.queryForList("SELECT workflow_id,reserved_bytes,execution_state,status FROM workflow_instance WHERE kind='SKILL_DOWNLOAD' AND owner_user_id=? AND (execution_state IN ('RESERVED','RUNNING','NEEDS_REVIEW') OR (execution_state IS NULL AND status IN ('DOWNLOADING','NEEDS_REVIEW')))",owner))
            result.put((String)row.get("workflow_id"),row.get("execution_state")==null?SkillDownloadLeases.PACKAGE_BYTES:((Number)row.get("reserved_bytes")).longValue());
        return result;
    }
    private Map<String,Object> execution(WorkflowRecord row) {
        return jdbc.queryForMap("SELECT execution_state,reserved_bytes,exit_verified,execution_deadline FROM workflow_instance WHERE id=? FOR UPDATE",row.id());
    }
    void reserve(long owner,String id) {
        var before=row(owner,id,true);var now=workflows.now();
        if(!"DOWNLOADING".equals(before.status())||execution(before).get("execution_state")!=null)throw conflict("下载预留已经存在");
        var p=payload(before).withLease(new LeaseEvidenceV1(null,null,null,now,now));
        changed(jdbc.update("UPDATE workflow_instance SET execution_state='RESERVED',reserved_bytes=?,exit_verified=FALSE,execution_deadline=?,payload_json=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE id=? AND revision=? AND execution_state IS NULL",SkillDownloadLeases.PACKAGE_BYTES,now.plusMinutes(5),write(p),before.id(),before.revision()));
        event(owner,id,"QUOTA_RESERVED","RESERVED");
    }
    Claim claim(long owner,String id,String worker) {
        var before=row(owner,id,true);var e=execution(before);var deadline=time(e.get("execution_deadline"));
        if(!"DOWNLOADING".equals(before.status())||!"RESERVED".equals(e.get("execution_state"))||deadline==null||!deadline.isAfter(workflows.now()))return null;
        var old=payload(before).lease();var p=payload(before).withLease(new LeaseEvidenceV1(worker,null,null,old.createdAt(),workflows.now()));
        var claimed=workflows.claim(before,"DOWNLOADING",p,null,null,Duration.ofMinutes(5));
        changed(jdbc.update("UPDATE workflow_instance SET execution_state='RUNNING',execution_deadline=? WHERE id=? AND revision=? AND fence=? AND claim_token=?",claimed.leaseExpiresAt(),claimed.id(),claimed.revision(),claimed.fence(),claimed.claimToken()));
        event(owner,id,"DOWNLOAD_CLAIMED","RUNNING");return new Claim(claimed.claimToken(),claimed.fence(),worker);
    }
    void process(long owner,String id,Claim claim,Process process) {
        var before=claimed(owner,id,claim);var old=payload(before).lease();var p=payload(before).withLease(new LeaseEvidenceV1(claim.worker(),process.pid(),process.info().startInstant().map(Object::toString).orElse(null),old.createdAt(),workflows.now()));
        changed(jdbc.update("UPDATE workflow_instance SET payload_json=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE id=? AND revision=? AND claim_token=? AND fence=? AND lease_expires_at>UTC_TIMESTAMP(6)",write(p),before.id(),before.revision(),claim.token(),claim.fence()));
        event(owner,id,"PROCESS_REGISTERED","RUNNING");
    }
    void seal(long owner,String id,Claim claim) {
        var before=claimed(owner,id,claim);var p=updatedLease(before);
        changed(jdbc.update("UPDATE workflow_instance SET execution_state='SEALED',reserved_bytes=0,exit_verified=TRUE,claim_token=NULL,lease_expires_at=NULL,payload_json=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE id=? AND revision=? AND claim_token=? AND fence=? AND lease_expires_at>UTC_TIMESTAMP(6)",write(p),before.id(),before.revision(),claim.token(),claim.fence()));
        event(owner,id,"PACKAGE_SEALED","SEALED");
    }
    private WorkflowRecord claimed(long owner,String id,Claim claim) {
        if(claim==null)throw conflict("缺少下载执行凭据");var before=row(owner,id,true);var p=payload(before);
        if(!"RUNNING".equals(execution(before).get("execution_state"))||!Objects.equals(claim.token(),before.claimToken())||claim.fence()!=before.fence()
                ||before.leaseExpiresAt()==null||!before.leaseExpiresAt().isAfter(workflows.now())||p.lease()==null||!Objects.equals(claim.worker(),p.lease().workerInstance()))throw conflict("下载执行租约已变化");
        return before;
    }
    void failed(long owner,String id,Claim claim,String worker,boolean exit,String code) {
        var before=row(owner,id,true);var e=execution(before);String phase=(String)e.get("execution_state");
        if(phase==null||Set.of("SEALED","RELEASED").contains(phase))return;
        var lease=payload(before).lease();
        if(!"RESERVED".equals(phase)&&(claim==null||claim.fence()!=before.fence()||before.claimToken()!=null&&!Objects.equals(claim.token(),before.claimToken())||!Objects.equals(claim.worker(),worker)||lease==null||!Objects.equals(worker,lease.workerInstance())))return;
        if(!Set.of("DOWNLOADING","DOWNLOADED","NEEDS_REVIEW").contains(before.status()))return;
        DOWNLOAD.requireTransition(before.status(),exit?"ERROR":"NEEDS_REVIEW");
        changed(jdbc.update("UPDATE workflow_instance SET status=?,error_code=?,execution_state=?,reserved_bytes=?,exit_verified=?,claim_token=NULL,lease_expires_at=NULL,payload_json=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE id=? AND revision=? AND fence=?",exit?"ERROR":"NEEDS_REVIEW",code,exit?"RELEASED":"NEEDS_REVIEW",exit?0:SkillDownloadLeases.PACKAGE_BYTES,exit,write(updatedLease(before)),before.id(),before.revision(),before.fence()));
        event(owner,id,exit?"EXIT_CONFIRMED":"EXIT_UNVERIFIED",exit?"RELEASED":"NEEDS_REVIEW");
    }
    List<Map<String,Object>> expired() {
        return jdbc.queryForList("SELECT workflow_id AS download_id,owner_user_id FROM workflow_instance WHERE kind='SKILL_DOWNLOAD' AND legacy_clock_json IS NULL AND ((execution_state IN ('RESERVED','RUNNING') AND execution_deadline<UTC_TIMESTAMP(6)) OR (execution_state IS NULL AND status='DOWNLOADING' AND updated_at<TIMESTAMPADD(MINUTE,-5,UTC_TIMESTAMP(6)))) ORDER BY id LIMIT 50");
    }
    void expire(long owner,String id) {
        var before=row(owner,id,true);var e=execution(before);String phase=(String)e.get("execution_state");var now=workflows.now();
        if(phase==null){
            if("DOWNLOADING".equals(before.status())&&before.updatedAt().isBefore(now.minusMinutes(5))){
                var after=workflows.transition(before,"NEEDS_REVIEW",payload(before),null,null,null);error(after,"DOWNLOAD_EXIT_UNVERIFIED");
            }return;
        }
        var deadline=time(e.get("execution_deadline"));if(!Set.of("RESERVED","RUNNING").contains(phase)||deadline==null||!deadline.isBefore(now))return;
        boolean unstarted="RESERVED".equals(phase);String state=unstarted?"RELEASED":"NEEDS_REVIEW";
        // Unknown exits keep all reserved bytes. No synthetic process success and no automatic reclaim.
        changed(jdbc.update("UPDATE workflow_instance SET execution_state=?,reserved_bytes=?,exit_verified=?,error_code=CASE WHEN status='DOWNLOADING' THEN ? ELSE error_code END,status=CASE WHEN status='DOWNLOADING' THEN ? ELSE status END,claim_token=NULL,lease_expires_at=NULL,payload_json=?,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE id=? AND revision=?",state,unstarted?0:SkillDownloadLeases.PACKAGE_BYTES,unstarted,unstarted?"DOWNLOAD_NOT_STARTED":"DOWNLOAD_EXIT_UNVERIFIED",unstarted?"ERROR":"NEEDS_REVIEW",write(updatedLease(before)),before.id(),before.revision()));
        event(owner,id,unstarted?"UNSTARTED_EXPIRED":"RESTART_NEEDS_REVIEW",state);
    }
    private DownloadV1 updatedLease(WorkflowRecord before){var p=payload(before);var old=p.lease();return p.withLease(new LeaseEvidenceV1(old.workerInstance(),old.processPid(),old.processStartedAt(),old.createdAt(),workflows.now()));}
    private void event(long owner,String id,String action,String status) {
        audits.append(new AuditEvent("SKILL_DOWNLOAD_EVENT",owner,null,"SKILL_DOWNLOAD",id,null,null,null,null,action,null,null,null,1,new DownloadEventV1(status)));
    }
    List<Map<String,Object>> cleanupCommands(long owner,String request,boolean lock) {
        var record=lock?workflows.findByRequestLocked(WorkflowKind.SKILL_STORAGE_COMMAND,"OWNER:"+owner,request):workflows.findByRequest(WorkflowKind.SKILL_STORAGE_COMMAND,"OWNER:"+owner,request);
        return record.map(value->List.of(cleanupView(value))).orElseGet(List::of);
    }
    List<Map<String,Object>> cleanupHistory(long owner){return workflows.list(WorkflowKind.SKILL_STORAGE_COMMAND,owner,null,null,Set.of(),false,50,false).stream().map(this::cleanupView).toList();}
    private Map<String,Object> cleanupView(WorkflowRecord row) {
        var p=workflows.payload(row,CleanupV1.class);var view=new LinkedHashMap<String,Object>();
        view.put("request_id",row.requestId());view.put("request_sha256",row.requestSha256());view.put("download_id",p.downloadId());view.put("status",row.status());
        view.put("removed_bytes",p.removedBytes());view.put("removed_files",p.removedFiles());view.put("error_code",row.errorCode());view.put("created_at",row.createdAt());view.put("updated_at",row.updatedAt());return view;
    }
    void beginCleanup(long owner,String request,String digest,String id) {
        workflows.create(new WorkflowDraft(UUID.randomUUID().toString(),WorkflowKind.SKILL_STORAGE_COMMAND,"OWNER:"+owner,request,digest,owner,owner,null,
                "SKILL_DOWNLOAD",id,1L,null,null,"STARTED",null,1,new CleanupV1(id,0,0)));
    }
    void purging(long owner,String id){var before=row(owner,id,true);if(!"PURGING".equals(before.status()))workflows.transition(before,"PURGING",payload(before),null,null,null);}
    void cleaned(long owner,String id,String request,long bytes,int files) {
        var download=row(owner,id,true);workflows.transition(download,"PURGED",payload(download),null,null,null);
        var command=workflows.findByRequestLocked(WorkflowKind.SKILL_STORAGE_COMMAND,"OWNER:"+owner,request).orElseThrow();
        workflows.transition(command,"COMPLETED",new CleanupV1(id,bytes,files),null,null,null);
        jdbc.update("UPDATE content_asset SET lifecycle='ARCHIVED',updated_at=UTC_TIMESTAMP(6) WHERE asset_kind='SKILL_IMPORT' AND asset_id=? AND owner_user_id=?",id,owner);
    }
    void cleanupError(long owner,String id,String request) {
        var before=row(owner,id,true);if("PURGING".equals(before.status()))workflows.transition(before,"CLEANUP_ERROR",payload(before),null,null,null);
        var command=workflows.findByRequestLocked(WorkflowKind.SKILL_STORAGE_COMMAND,"OWNER:"+owner,request).orElseThrow();
        if("STARTED".equals(command.status()))error(workflows.transition(command,"ERROR",workflows.payload(command,CleanupV1.class),null,null,null),"CLEANUP_RESULT_UNVERIFIED");
    }
    private void error(WorkflowRecord row,String code){changed(jdbc.update("UPDATE workflow_instance SET error_code=? WHERE id=? AND revision=?",code,row.id(),row.revision()));}
    private static void changed(int count){if(count!=1)throw conflict("技能下载状态已变化");}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalArgumentException("Cannot encode skill workflow",error);}}
    private static String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException(error);}}
    private static LocalDateTime time(Object value){return value==null?null:value instanceof LocalDateTime time?time:((java.sql.Timestamp)value).toLocalDateTime();}
    private static RuntimeException conflict(String message){return new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,message);}
}
