package com.ruanzhu.doorhandle.module.detection.service.detection;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.contracts.detection.*;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService;
import com.ruanzhu.doorhandle.module.infra.service.OssStorageService;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.*;
import jakarta.annotation.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.io.ByteArrayInputStream;

/** Owns approved creation commands. Only receipt-proven, complete transfers become dispatchable tasks. */
@Service
@ConditionalOnProperty(prefix="detection.creation",name="enabled",havingValue="true")
public class DetectionCreationService implements DetectionCreationApi {
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final ObjectMapper json;
    private final PlatformTransactionManager transactions;private DetectionCreationTransfers transfers;private DetectionCreationReview review;
    @Value("${detection.creation.transfer-evidence-enabled:false}") private boolean transferEvidenceEnabled;
    @Value("${detection.creation.business-images-enabled:false}") private boolean businessImagesEnabled;
    @Value("${detection.creation.review-enabled:false}") private boolean reviewEnabled;
    private final ObjectProvider<WorkspaceDetectionImagesApi> images;private final DetectionModelSelectionApi models;
    private final BusinessUserDirectory users;private final OperationsAuditApi audit;private final OssStorageService oss;
    private final DetectionTaskMapper tasks;private final DetectionDispatchOutbox outbox;private final ObjectProvider<DetectionIdentityService> identities;
    private final ExecutorService executor=Executors.newSingleThreadExecutor(r->{var t=new Thread(r,"approved-detection-creation");t.setDaemon(true);return t;});
    private final AtomicBoolean busy=new AtomicBoolean();
    private final ExecutorService reviewExecutor=Executors.newSingleThreadExecutor(r->{var t=new Thread(r,"detection-transfer-review");t.setDaemon(true);return t;});
    private final AtomicBoolean reviewBusy=new AtomicBoolean();
    @Value("${detection.max-images-per-batch:200}") private int maxImages=200;
    @Value("${detection.max-image-bytes:10485760}") private long maxImageBytes=10485760;
    public DetectionCreationService(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,ObjectProvider<WorkspaceDetectionImagesApi> images,
            DetectionModelSelectionApi models,BusinessUserDirectory users,OperationsAuditApi audit,OssStorageService oss,
            DetectionTaskMapper tasks,DetectionDispatchOutbox outbox,ObjectProvider<DetectionIdentityService> identities){
        this.jdbc=jdbc;tx=new TransactionTemplate(manager);this.transactions=manager;this.json=json;this.images=images;this.models=models;this.users=users;this.audit=audit;this.oss=oss;this.tasks=tasks;this.outbox=outbox;this.identities=identities;
    }
    @PostConstruct public void validate(){
        if(maxImages<1||maxImageBytes<1||maxImageBytes>26214400)throw new IllegalStateException("检测图片限制配置无效");
        if((businessImagesEnabled||reviewEnabled)&&!transferEvidenceEnabled)throw new IllegalStateException("业务原图及核对功能需要持久传输证据");
        jdbc.queryForList("SELECT command_id,preview_sha256,owner_token FROM detection_creation_job WHERE 1=0");jdbc.queryForList("SELECT user_id FROM detection_creation_owner WHERE 1=0");
        if(transferEvidenceEnabled){if(!oss.isConfigured())throw new IllegalStateException("批准传输需要配置对象存储");transfers=new DetectionCreationTransfers(jdbc,transactions,json,oss,audit);transfers.schema();}
        if(reviewEnabled){review=new DetectionCreationReview(jdbc,transactions,json,oss,audit,transfers,new DetectionCreationReview.Access(){
            public Preview validate(AgentActor actor,Map<String,Object> job){
                current(actor);if(!actor.role().name().equals(job.get("actor_role"))||!actor.username().equals(job.get("actor_username")))throw new SecurityException("原批准账号或角色已变化 请终止后重新生成提议");
                var approved=decode(job);revalidate(actor,approved);return approved;
            }
            public void validateImage(AgentActor actor,Preview approved,WorkspaceDetectionImagesApi.Image image){current(actor);images.getObject().assertUnchanged(actor,approved.sessionId(),List.of(image));}
            public void publish(AgentActor actor,Map<String,Object> job,Preview approved){var manifest=transfers.manifest(job,approved);publishTask(job,actor,approved,manifest.prefix(),manifest.keys(),"NEEDS_REVIEW");}
        });review.schema();}
    }
    private AgentActor current(AgentActor actor){if(actor==null)throw new SecurityException("缺少账号身份");var now=users.current(actor.userId(),actor.username());if(now.userId()!=actor.userId()||!now.username().equals(actor.username())||now.supervisor()!=actor.supervisor())throw new SecurityException("账号身份或角色已变化");return actor;}
    @Override public Preview preview(AgentActor actor,String session,Request request){
        current(actor);if(session==null||!session.matches("[A-Za-z0-9_.-]{1,128}"))throw new IllegalArgumentException("会话编号无效");
        if(request==null||request.capture()==null)throw new IllegalArgumentException("请先补齐采集日期、区域、采集人、设备和批次文件夹");
        var capture=request.capture();try{if(capture.captureDate()==null||!capture.captureDate().matches("[0-9]{4}-[0-9]{2}-[0-9]{2}"))throw new IllegalArgumentException();LocalDate.parse(capture.captureDate());}catch(Exception invalid){throw new IllegalArgumentException("请提供有效采集日期 YYYY-MM-DD");}
        for(String value:Arrays.asList(capture.region(),capture.collector(),capture.deviceName(),capture.imageFolderName()))
            if(value==null||value.isBlank()||value.length()>64||value.chars().anyMatch(Character::isISOControl))throw new IllegalArgumentException("请补齐区域、采集人、设备和批次文件夹，每项最多 64 字");
        if((capture.captureDate()+"_"+capture.region()+"_"+capture.deviceName()+"_"+capture.imageFolderName()).length()>128)throw new IllegalArgumentException("采集日期、区域、设备及批次文件夹组合不能超过 128 字");
        BigDecimal threshold=request.threshold()==null?new BigDecimal("0.5"):request.threshold().stripTrailingZeros();
        if(threshold.compareTo(BigDecimal.ZERO)<0||threshold.compareTo(BigDecimal.ONE)>0)throw new IllegalArgumentException("阈值应在 0 到 1 之间");
        var source=images.getIfAvailable();if(source==null)throw new IllegalStateException("会话文件服务未启用");
        if(request.fileIds().size()+request.businessImages().size()<1||request.fileIds().size()+request.businessImages().size()>maxImages)throw new IllegalArgumentException("请提供有效数量的会话图片或已关联业务原图");
        var all=new ArrayList<WorkspaceDetectionImagesApi.Image>();if(!request.fileIds().isEmpty())all.addAll(source.describe(actor,session,request.fileIds()));if(!request.businessImages().isEmpty())all.addAll(source.describeBusiness(actor,session,request.businessImages()));var files=List.copyOf(all);
        if(files.stream().map(WorkspaceDetectionImagesApi.Image::fileId).distinct().count()!=files.size())throw new IllegalArgumentException("图片编号不能重复");
        if(files.size()>maxImages||files.stream().anyMatch(file->file.bytes()<1||file.bytes()>maxImageBytes))throw new IllegalArgumentException("图片数量或大小超过检测限制");
        var model=models.select(request.modelId());
        String version=resourceVersion(session,files,model,threshold,capture);
        return new Preview(session,files,model,threshold,capture,version);
    }
    @Override public void assertReadable(AgentActor actor,Preview approved){current(actor);var source=images.getIfAvailable();if(source==null)throw new IllegalStateException("会话文件服务未启用");source.assertUnchanged(actor,approved.sessionId(),approved.images());}
    @Override public void revalidate(AgentActor actor,Preview approved){
        assertReadable(actor,approved);
        if(approved.images().isEmpty()||approved.images().size()>maxImages||approved.images().stream().anyMatch(file->file.bytes()<1||file.bytes()>maxImageBytes)||!models.select(approved.model().id()).equals(approved.model())||!resourceVersion(approved.sessionId(),approved.images(),approved.model(),approved.threshold(),approved.capture()).equals(approved.resourceVersion()))throw new DetectionExecutionApi.ResourceChanged();
    }
    private record LegacyImage(String fileId,String name,String contentType,long bytes,String sha256,String previewPath){}
    private String resourceVersion(String session,List<WorkspaceDetectionImagesApi.Image> files,DetectionModelSelectionApi.Model model,BigDecimal threshold,Capture capture){
        // Old approved private-image commands retain their original resource digest across the DTO extension.
        Object source=files.stream().allMatch(file->file.origin()==null)?files.stream().map(file->new LegacyImage(file.fileId(),file.name(),file.contentType(),file.bytes(),file.sha256(),file.previewPath())).toList():files;
        return hash(write(List.of(session,source,model,threshold,capture)));
    }
    @Override @Transactional public Receipt reserve(AgentActor actor,String requestId,String proposalId,Preview approved){
        if(!TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("创建检测需要确认事务");
        current(actor);token(requestId);token(proposalId);if(approved==null)throw new IllegalArgumentException("缺少已批准提议");
        jdbc.update("INSERT INTO detection_creation_owner(user_id) VALUES(?) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id)",actor.userId());
        jdbc.queryForObject("SELECT user_id FROM detection_creation_owner WHERE user_id=? FOR UPDATE",Long.class,actor.userId());
        var previous=jdbc.queryForList("SELECT * FROM detection_creation_job WHERE actor_user_id=? AND request_id=?",actor.userId(),requestId);
        String body=write(approved),digest=hash(body);
        if(!previous.isEmpty()){var row=previous.get(0);if(!digest.equals(row.get("preview_sha256"))||!proposalId.equals(row.get("proposal_id")))throw new IllegalArgumentException("请求编号已用于其他图片或参数");return receipt(row);}
        revalidate(actor,approved);
        Long pending=jdbc.queryForObject("SELECT COUNT(*) FROM detection_creation_job j WHERE actor_user_id=? AND (status IN ('PREPARING','UPLOADING','NEEDS_REVIEW')"+(transfers==null?"":" OR (status='CANCELLED' AND EXISTS (SELECT 1 FROM detection_creation_object o WHERE o.command_id=j.command_id AND o.state='UPLOADING'))")+")",Long.class,actor.userId());
        if(pending>=16)throw new IllegalStateException("本人未完成的检测创建命令已达上限，请先核对已有任务");
        String command=UUID.randomUUID().toString(),task="det_"+UUID.randomUUID().toString().replace("-",""),dispatch=UUID.randomUUID().toString();
        jdbc.update("INSERT INTO detection_creation_job(command_id,actor_user_id,actor_username,actor_role,request_id,proposal_id,task_id,dispatch_id,session_id,preview_json,preview_sha256,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'PREPARING',CURRENT_TIMESTAMP(6),CURRENT_TIMESTAMP(6))",
                command,actor.userId(),actor.username(),actor.role().name(),requestId,proposalId,task,dispatch,approved.sessionId(),body,digest);
        if(transfers!=null)transfers.prepare(actor,command,task,requestId,approved);
        audit(actor,task,requestId,"CREATE_APPROVED","PREPARING");return new Receipt(command,task,dispatch,"PREPARING");
    }
    @Override public Optional<Receipt> receipt(AgentActor actor,String requestId){current(actor);token(requestId);var rows=jdbc.queryForList("SELECT * FROM detection_creation_job WHERE actor_user_id=? AND request_id=?",actor.userId(),requestId);if(rows.isEmpty())return Optional.empty();var row=rows.get(0);assertReadable(actor,decode(row));return Optional.of(receipt(row));}
    @Override public List<Receipt> jobs(AgentActor actor,String session,int limit){
        current(actor);if(session==null||!session.matches("[A-Za-z0-9_.-]{1,128}")||limit<1||limit>50)throw new IllegalArgumentException("创建任务查询参数无效");
        return jdbc.queryForList("SELECT command_id,task_id,dispatch_id,status FROM detection_creation_job WHERE actor_user_id=? AND session_id=? AND status IN ('PREPARING','UPLOADING','NEEDS_REVIEW') ORDER BY id DESC LIMIT ?",actor.userId(),session,limit).stream().map(this::receipt).toList();
    }
    private Receipt receipt(Map<String,Object> row){return new Receipt((String)row.get("command_id"),(String)row.get("task_id"),(String)row.get("dispatch_id"),(String)row.get("status"));}
    @Override public List<TransferReview> transferReviews(AgentActor actor,String session){current(actor);session(session);return review==null?List.of():review.list(actor,session);}
    @Override public TransferReview reviewTransfer(AgentActor actor,String session,String command,ReviewCommand input){current(actor);session(session);token(command);if(review==null)throw new IllegalStateException("检测文件核对尚未启用");return review.command(actor,session,command,input);}
    private static void session(String session){if(session==null||!session.matches("[A-Za-z0-9_.-]{1,128}"))throw new IllegalArgumentException("会话编号无效");}
    private Preview decode(Map<String,Object> row){String body=(String)row.get("preview_json");if(!hash(body).equals(row.get("preview_sha256")))throw new IllegalStateException("已批准创建命令摘要不匹配");try{return json.readValue(body,Preview.class);}catch(Exception error){throw new IllegalStateException("已批准创建命令不可读取");}}
    @Scheduled(fixedDelay=1000) public void schedule(){if(!busy.compareAndSet(false,true))return;try{executor.submit(()->{try{poll();}catch(RuntimeException unavailable){org.slf4j.LoggerFactory.getLogger(getClass()).warn("Detection creation scheduler unavailable; commands remain pending reconciliation");}finally{busy.set(false);}});}catch(RejectedExecutionException stopped){busy.set(false);}}
    @Scheduled(fixedDelay=2000) public void scheduleReviews(){if(review==null||!reviewBusy.compareAndSet(false,true))return;try{reviewExecutor.submit(()->{try{review.poll();}catch(RuntimeException unavailable){org.slf4j.LoggerFactory.getLogger(getClass()).warn("Detection transfer check remains unconfirmed");}finally{reviewBusy.set(false);}});}catch(RejectedExecutionException stopped){reviewBusy.set(false);}}
    private void poll(){
        // Expired ownership never authorizes a second transfer. Keep the directory and original command for reconciliation.
        for(var expired:jdbc.queryForList("SELECT id FROM detection_creation_job WHERE status='UPLOADING' AND lease_until<CURRENT_TIMESTAMP(6) ORDER BY id LIMIT 8"))try{
            tx.executeWithoutResult(status->{var rows=jdbc.queryForList("SELECT * FROM detection_creation_job WHERE id=? AND status='UPLOADING' AND lease_until<CURRENT_TIMESTAMP(6) FOR UPDATE SKIP LOCKED",expired.get("id"));if(!rows.isEmpty())markReview(rows.get(0),"TRANSFER_INTERRUPTED");});
        }catch(RuntimeException unavailable){org.slf4j.LoggerFactory.getLogger(getClass()).warn("Detection creation reconciliation pending, job={}",expired.get("id"));}
        var row=tx.execute(status->{var ready=jdbc.queryForList("SELECT * FROM detection_creation_job WHERE status='PREPARING' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED");if(ready.isEmpty())return null;var job=ready.get(0);String owner=UUID.randomUUID().toString();
            if(transfers!=null&&job.get("manifest_sha256")==null){
                var actor=new AgentActor(((Number)job.get("actor_user_id")).longValue(),(String)job.get("actor_username"),AgentActor.Role.valueOf((String)job.get("actor_role")));
                // Recording an immutable target is not permission to transfer; current identity is checked after claim.
                // Do not let a revoked legacy owner block all other owners at the head of the preparation queue.
                transfers.prepare(actor,(String)job.get("command_id"),(String)job.get("task_id"),(String)job.get("request_id"),decode(job));job=jdbc.queryForMap("SELECT * FROM detection_creation_job WHERE id=?",job.get("id"));
            }
            jdbc.update("UPDATE detection_creation_job SET status='UPLOADING',owner_token=?,lease_until=DATE_ADD(CURRENT_TIMESTAMP(6),INTERVAL 15 MINUTE),updated_at=CURRENT_TIMESTAMP(6)"+(transfers!=null?",revision=revision+1":"")+" WHERE id=? AND status='PREPARING'",owner,job.get("id"));job.put("owner_token",owner);return job;});
        if(row==null)return;
        try{transfer(row);}catch(RuntimeException failure){
            // No exception message or private content is stored. A committed completion is not overwritten after lost acknowledgement.
            tx.executeWithoutResult(status->markReview(row,"TRANSFER_OR_COMMIT_UNCONFIRMED"));
        }
    }
    private void transfer(Map<String,Object> row){
        var approved=decode(row);var actor=current(new AgentActor(((Number)row.get("actor_user_id")).longValue(),(String)row.get("actor_username"),AgentActor.Role.valueOf((String)row.get("actor_role"))));
        revalidate(actor,approved);
        if(!oss.isConfigured())throw new IllegalStateException("OSS 未配置");
        var manifest=transfers==null?null:transfers.manifest(row,approved);
        String prefix=manifest==null?oss.normalizeBasePrefix()+"/agent-approved/"+actor.userId()+"/"+row.get("task_id")+"/Original/":manifest.prefix();
        var keys=new ArrayList<String>();
        for(var file:approved.images()){
            if(jdbc.update("UPDATE detection_creation_job SET lease_until=DATE_ADD(CURRENT_TIMESTAMP(6),INTERVAL 15 MINUTE),updated_at=CURRENT_TIMESTAMP(6) WHERE id=? AND owner_token=? AND status='UPLOADING' AND lease_until>CURRENT_TIMESTAMP(6)",row.get("id"),row.get("owner_token"))!=1)throw new IllegalStateException("创建命令执行权已失效");
            current(actor);byte[] data=images.getObject().read(actor,approved.sessionId(),file);
            String key=manifest==null?prefix+file.fileId()+"-"+file.sha256()+(file.contentType().equals("image/png")?".png":".jpg"):manifest.keys().get(keys.size());
            if(transfers==null)oss.putObject(key,new ByteArrayInputStream(data),data.length,file.contentType());else transfers.upload(row,actor,file,key,data);keys.add(key);
        }
        tx.executeWithoutResult(status->{
            var locked=jdbc.queryForMap("SELECT * FROM detection_creation_job WHERE id=? FOR UPDATE",row.get("id"));
            if(!"UPLOADING".equals(locked.get("status"))||!Objects.equals(row.get("owner_token"),locked.get("owner_token")))throw new IllegalStateException("创建命令执行权已变化");
            if(transfers!=null){transfers.manifest(locked,approved);transfers.assertStored((String)row.get("command_id"),approved.images().size());}
            publishTask(locked,actor,approved,prefix,keys,"UPLOADING");
        });
    }
    /** SQL-only finalization, shared by original execution and an explicit verified recovery decision. */
    private void publishTask(Map<String,Object> row,AgentActor actor,Preview approved,String prefix,List<String> keys,String expectedStatus){
            if(!TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("检测创建必须在业务事务内完成");
            current(actor);revalidate(actor,approved);
            if(!expectedStatus.equals(row.get("status")))throw new IllegalStateException("创建命令状态已变化");
            var p=approved.capture();var task=new DetectionTask();String taskId=(String)row.get("task_id");
            task.setTaskId(taskId);task.setWorkflowUuid(UUID.randomUUID().toString());task.setTaskType(approved.images().size()==1?"SINGLE":"BATCH");
            task.setBatchNo(p.captureDate()+"_"+p.region()+"_"+p.deviceName()+"_"+p.imageFolderName());task.setWorkOrderNo("WO-"+row.get("command_id"));
            task.setStatus("QUEUED");task.setStage("QUEUED");task.setFlowStatus("PENDING_DETECTION");task.setReviewStatus("PENDING");task.setDispositionStatus("PENDING");
            task.setDispatchId((String)row.get("dispatch_id"));task.setModelId(approved.model().id());task.setModelVersion(approved.model().version());task.setThreshold(approved.threshold());
            task.setCaptureDate(p.captureDate());task.setRegion(p.region());task.setCollector(p.collector());task.setDeviceName(p.deviceName());task.setImageFolderName(p.imageFolderName());
            task.setTotalImages(keys.size());task.setProcessedImages(0);task.setSuccessfulImages(0);task.setFailedImages(0);task.setSourceOssPrefix(prefix);task.setOriginalImageKeysJson(write(keys));
            task.setSessionId(approved.sessionId());task.setCreatedBy(actor.username());task.setCreatedAt(LocalDateTime.now(ZoneOffset.ofHours(8)));task.setUpdatedAt(task.getCreatedAt());
            tasks.insert(task);var identity=identities.getIfAvailable();if(identity!=null)identity.recordCreation(task,actor,(String)row.get("request_id"));models.recordUse(approved.model());
            var event=DetectionTaskCreatedEvent.builder().eventId(UUID.randomUUID().toString()).eventType("DETECTION_TASK_CREATED").eventTime(OffsetDateTime.now(ZoneOffset.ofHours(8)).toString())
                    .taskId(taskId).dispatchId(task.getDispatchId()).bucketName(oss.getBucketName()).sourcePrefix(prefix).originalKeys(keys).modelId(approved.model().id()).threshold(approved.threshold())
                    .captureInfo(DetectionTaskEventCaptureInfo.builder().captureDate(p.captureDate()).region(p.region()).collector(p.collector()).deviceName(p.deviceName()).imageFolderName(p.imageFolderName()).build()).build();
            outbox.enqueue(event,actor,(String)row.get("request_id"));audit(actor,taskId,(String)row.get("request_id"),"CREATE_QUEUED","QUEUED");
            var receipt=new DetectionExecutionApi.Receipt((String)row.get("command_id"),"CREATE",taskId,task.getDispatchId(),"QUEUED");
            jdbc.update("INSERT INTO detection_execution_command(command_id,actor_user_id,request_id,command_type,payload_sha256,proposal_id,task_id,dispatch_id,result_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",receipt.commandId(),actor.userId(),row.get("request_id"),"CREATE",row.get("preview_sha256"),row.get("proposal_id"),taskId,task.getDispatchId(),write(receipt));
            String ownership="UPLOADING".equals(expectedStatus)?" AND owner_token=? AND lease_until>CURRENT_TIMESTAMP(6)":"";
            Object[] args="UPLOADING".equals(expectedStatus)?new Object[]{row.get("id"),expectedStatus,row.get("owner_token")}:new Object[]{row.get("id"),expectedStatus};
            if(jdbc.update("UPDATE detection_creation_job SET status='QUEUED',reason_code=NULL,updated_at=CURRENT_TIMESTAMP(6)"+(transfers!=null?",revision=revision+1":"")+" WHERE id=? AND status=?"+ownership,args)!=1)throw new IllegalStateException("创建命令执行权或期限已变化");
    }
    private void markReview(Map<String,Object> row,String reason){
        int changed=jdbc.update("UPDATE detection_creation_job SET status='NEEDS_REVIEW',reason_code=?,updated_at=CURRENT_TIMESTAMP(6)"+(transfers!=null?",revision=revision+1":"")+" WHERE id=? AND owner_token=? AND status='UPLOADING'",reason,row.get("id"),row.get("owner_token"));
        if(changed==1)audit(new AgentActor(((Number)row.get("actor_user_id")).longValue(),(String)row.get("actor_username"),AgentActor.Role.valueOf((String)row.get("actor_role"))),
                (String)row.get("task_id"),(String)row.get("request_id"),"CREATE_NEEDS_REVIEW","NEEDS_REVIEW");
    }
    private void audit(AgentActor actor,String resource,String request,String action,String result){audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DETECTION",action,resource,request,result,null));}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception failure){throw new IllegalStateException("检测创建参数不可序列化");}}
    private static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception failure){throw new IllegalStateException(failure);}}
    private static void token(String value){if(value==null||!value.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("创建请求编号无效");}
    @PreDestroy public void close(){executor.shutdownNow();reviewExecutor.shutdownNow();}
}
