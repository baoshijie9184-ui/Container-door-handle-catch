package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.function.Supplier;

@Service
@ConditionalOnProperty(prefix="agentscope.workbench",name="enabled",havingValue="true")
public class AgentWorkspaceService implements WorkbenchSessionApi {
    private final ChatSessionService sessions;private final BusinessUserDirectory users;private final ObjectProvider<ConversationInboxService> inbox;
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final Path root;private final long maxBytes,quotaBytes;private final WorkspacePersistence store;
    @Value("${agentscope.workbench.preview-bytes:64000}") private int previewBytes=64000;
    private ObjectProvider<AgentBusinessFilesApi> business;
    private ObjectProvider<DetectionAgentReadApi> detection;
    private ObjectProvider<DetectionCreationApi> creation;
    private ObjectProvider<ContextFileAccessApi> contextAccess;
    private ObjectProvider<WorkspaceTurnSnapshotService> turnSnapshots;
    @org.springframework.beans.factory.annotation.Autowired public void setTurnSnapshots(ObjectProvider<WorkspaceTurnSnapshotService> snapshots){turnSnapshots=snapshots;}
    @org.springframework.beans.factory.annotation.Autowired public void setContextAccess(ObjectProvider<ContextFileAccessApi> access){contextAccess=access;}
    @org.springframework.beans.factory.annotation.Autowired public void setCreation(ObjectProvider<DetectionCreationApi> creation){this.creation=creation;}
    @org.springframework.beans.factory.annotation.Autowired public void setDetection(ObjectProvider<DetectionAgentReadApi> detection){this.detection=detection;}
    @org.springframework.beans.factory.annotation.Autowired public void setBusiness(ObjectProvider<AgentBusinessFilesApi> business){this.business=business;}
    public AgentWorkspaceService(ChatSessionService sessions,BusinessUserDirectory users,ObjectProvider<ConversationInboxService> inbox,JdbcTemplate jdbc,PlatformTransactionManager manager,
            @Value("${agentscope.workbench.storage-root:${user.dir}/.agentscope/workspace/artifacts}") String root,
            @Value("${agentscope.workbench.max-file-bytes:26214400}") long maxBytes,@Value("${agentscope.workbench.quota-bytes:524288000}") long quotaBytes){
        this.sessions=sessions;this.users=users;this.inbox=inbox;this.jdbc=jdbc;store=new WorkspacePersistence(jdbc);tx=new TransactionTemplate(manager);tx.setTimeout(5);this.root=Path.of(root).toAbsolutePath().normalize();this.maxBytes=maxBytes;this.quotaBytes=quotaBytes;
    }
    @PostConstruct public void validate(){store.validate();jdbc.queryForList("SELECT fork_owner_user_id,fork_request_id,fork_source_session_id,fork_through_message_id FROM chat_session WHERE 1=0");if(maxBytes<1||quotaBytes<maxBytes||previewBytes<1||previewBytes>1048576)throw new IllegalStateException("文件配额或预览配置无效");}
    public Map<String,Long> limits(){return Map.of("maxFileBytes",maxBytes,"quotaBytes",quotaBytes,"previewBytes",(long)previewBytes);}
    @Override public void assertOwned(AgentActor actor,String session){var current=users.current(actor.userId(),actor.username());if(current.userId()!=actor.userId()||current.supervisor()!=actor.supervisor())throw new SecurityException("账号身份已变化");if(sessions.resolveTenantForSystemCallback(session).userId()!=actor.userId())throw fail(404,"会话不存在或无权限");sessions.verifySessionOwner(actor.username(),session);}
    private <T>T locked(long user,Supplier<T> work){return tx.execute(status->{JdbcOwnerLock.lock(jdbc, JdbcOwnerLock.Scope.WORKSPACE, user);return work.get();});}
    private static String hash(byte[] data){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));}catch(Exception error){throw new IllegalStateException(error);}}
    private static void request(String id){if(id==null||!id.matches("[A-Za-z0-9_-]{1,128}"))throw fail(400,"请求编号无效");}
    private void audit(AgentActor actor,String session,String resource,String action,String digest){store.audit(actor.userId(),session,resource,action,digest);}
    @Override public List<File> files(AgentActor actor,String session){assertOwned(actor,session);return store.files(actor.userId(),session);}
    public File requireFile(AgentActor actor,String session,String id){assertOwned(actor,session);return store.file(actor.userId(),session,id).orElseThrow(()->fail(404,"文件不存在或无权限"));}
    public void requireBusinessReference(AgentActor actor,String session,String kind,String resource){assertOwned(actor,session);if(!"DETECTION".equals(kind)||resource==null||!resource.matches("[A-Za-z0-9_-]{1,128}"))throw fail(400,"检测业务引用无效");if(!store.hasBusiness(actor.userId(),session,kind,resource))throw fail(403,"请先将有权访问的检测任务关联到当前会话");}
    private Path location(long user,String id,boolean create){
        if(id==null||!id.matches("[a-f0-9-]{36}"))throw fail(400,"文件编号无效");
        Path target=root.resolve("users").resolve(Long.toString(user)).resolve(id+".bin").normalize();
        if(!target.startsWith(root))throw fail(400,"文件路径无效");
        try{for(Path cursor=target;cursor!=null;cursor=cursor.getParent())if(Files.isSymbolicLink(cursor))throw fail(400,"文件路径包含链接");if(create)Files.createDirectories(target.getParent());return target;}catch(java.io.IOException error){throw fail(503,"文件存储不可用");}
    }
    public File upload(AgentActor actor,String session,String requestId,String name,byte[] bytes,String folder){
        assertOwned(actor,session);request(requestId);
        if(name==null||name.isBlank()||name.length()>200||name.matches(".*[\\\\/\\p{Cntrl}].*")||bytes.length==0||bytes.length>maxBytes)throw fail(400,"文件名或大小无效");
        String lower=name.toLowerCase(Locale.ROOT),mime;
        if(lower.endsWith(".png"))mime="image/png";else if(lower.endsWith(".jpg")||lower.endsWith(".jpeg"))mime="image/jpeg";else if(lower.endsWith(".webp"))mime="image/webp";else if(lower.endsWith(".pdf"))mime="application/pdf";
        else if(List.of(".txt",".md",".csv",".json",".html",".svg").stream().anyMatch(lower::endsWith))mime="text/plain; charset=utf-8";else throw fail(415,"不支持此文件格式");
        WorkspaceFileContent.validate(name,mime,bytes);
        final String contentType=mime,digest=hash(bytes);return locked(actor.userId(),()->{
            var old=store.byRequest(actor.userId(),requestId);
            if(old.isPresent()){var prior=old.get();if(!prior.sha256().equalsIgnoreCase(digest)||!prior.name().equals(name)||!prior.folder().equals(folder)||!store.hasFileReference(actor.userId(),session,prior.id()))throw fail(409,"请求编号已使用");return prior;}
            long used=store.usedBytes(actor.userId());if(used>quotaBytes-bytes.length)throw fail(413,"本人文件存储配额不足");
            String id=UUID.randomUUID().toString();Path target=location(actor.userId(),id,true);
            try(var output=Files.newOutputStream(target,StandardOpenOption.CREATE_NEW)){
                // A failed COMMIT acknowledgement is not proof of rollback. Keep its only file copy.
                org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(new org.springframework.transaction.support.TransactionSynchronization(){@Override public void afterCompletion(int status){if(status==STATUS_ROLLED_BACK)try{Files.deleteIfExists(target);}catch(java.io.IOException ignored){}}});
                output.write(bytes);
            }catch(java.io.IOException error){throw fail(503,"文件保存失败");}
            var file=new File(id,name,contentType,bytes.length,digest,folder);store.createFile(actor.userId(),session,requestId,file);audit(actor,session,id,"FILE_CREATED",digest);return file;
        });
    }
    @Override public File createArtifact(AgentActor actor,String session,String requestId,String name,String content){assertOwned(actor,session);if(name==null||!List.of(".md",".csv",".json").stream().anyMatch(name.toLowerCase(Locale.ROOT)::endsWith)||content==null||content.length()>500000)throw fail(400,"产物名称或内容无效");if(name.toLowerCase(Locale.ROOT).endsWith(".json"))WorkspaceFileContent.validateJson(content,400);return upload(actor,session,requestId,name,content.getBytes(StandardCharsets.UTF_8),"artifacts");}
    public byte[] bytes(AgentActor actor,String session,String id){var metadata=requireFile(actor,session,id);if("context".equals(metadata.folder())){if(contextAccess==null||contextAccess.getIfAvailable()==null)throw fail(503,"上下文资料的权限核对服务未启用");contextAccess.getObject().assertReadable(actor,session,id);}return bytesForContextValidation(actor,session,id);}
    byte[] bytesForContextValidation(AgentActor actor,String session,String id){var metadata=requireFile(actor,session,id);try{Path path=location(actor.userId(),id,false);if(Files.size(path)!=metadata.bytes()||Files.size(path)>maxBytes)throw fail(409,"文件长度已变化");byte[] data=Files.readAllBytes(path);if(!hash(data).equalsIgnoreCase(metadata.sha256()))throw fail(409,"文件摘要已变化");return data;}catch(java.io.IOException error){throw fail(404,"文件内容不可用");}}
    @Override public String readText(AgentActor actor,String session,String id){var metadata=requireFile(actor,session,id);if("context".equals(metadata.folder()))throw fail(403,"上下文卸载资料请通过当前 Agent 的 read_context_file 受控读取");byte[] data=bytes(actor,session,id);return WorkspaceFileContent.read(metadata.contentType(),data,previewBytes);}
    public record PdfPreview(byte[] png,int page,int pages){}
    public PdfPreview previewPdf(AgentActor actor,String session,String id,int page){var metadata=requireFile(actor,session,id);if(!metadata.contentType().equals("application/pdf"))throw fail(415,"此预览接口仅用于 PDF");var result=WorkspaceFileContent.previewPdf(bytes(actor,session,id),page);return new PdfPreview(result.png(),result.page(),result.pages());}
    public void remove(AgentActor actor,String session,String id,String requestId){assertOwned(actor,session);request(requestId);locked(actor.userId(),()->{
        String signature=hash((session+":"+id+":REMOVE").getBytes(StandardCharsets.UTF_8));if(store.hasMutation(actor.userId(),requestId,signature))return null;
        var metadata=requireFile(actor,session,id);if("context".equals(metadata.folder()))throw fail(409,"上下文资料仍被执行记录引用，暂不能移除");store.unlinkFile(actor.userId(),session,id);audit(actor,session,id,"FILE_UNLINKED",metadata.sha256());
        store.mutation(actor.userId(),requestId,signature);return null;
    });}
    @Override public void continueSession(AgentActor actor,String session,String requestId,String content){assertOwned(actor,session);inbox.getObject().enqueue(actor,session,requestId,"NEXT_TURN",content,"CHAT");}
    public Map<String,Object> lineage(AgentActor actor,String session){assertOwned(actor,session);var rows=jdbc.queryForList("SELECT fork_source_session_id AS source_session_id,fork_through_message_id AS through_message_id FROM chat_session WHERE user_id=? AND fork_owner_user_id=user_id AND session_id=? AND fork_request_id IS NOT NULL",actor.userId(),session);if(rows.isEmpty())return Map.of();return Map.of("sourceSessionId",rows.get(0).get("source_session_id"),"throughMessageId",rows.get(0).get("through_message_id"),"legacyFileBoundary",store.legacyBoundary(actor.userId(),session));}
    @Override public List<AgentWorkbenchApi.Item> externalJobs(AgentActor actor,String session){
        assertOwned(actor,session);var result=new ArrayList<AgentWorkbenchApi.Item>();
        if(creation!=null&&creation.getIfAvailable()!=null)for(var job:creation.getObject().jobs(actor,session,16)){
            String phase=job.status(),status=phase.equals("PREPARING")?"QUEUED":phase.equals("UPLOADING")?"RUNNING":"NEEDS_REVIEW";
            String text=phase.equals("PREPARING")?"已批准，等待准备检测文件":phase.equals("UPLOADING")?"正在复制已批准图片，尚未派发检测":"图片传输或创建结果待核对，不自动重复执行";
            result.add(new AgentWorkbenchApi.Item(UUID.nameUUIDFromBytes((actor.userId()+":create-detection:"+job.commandId()).getBytes(StandardCharsets.UTF_8)).toString(),"EXTERNAL_JOB",status,0,
                    Map.of("title","创建检测任务","source","DETECTION_CREATION","resourceId",job.taskId(),"commandId",job.commandId(),"managementPath","/agent/actions","text",text),null));
        }
        if(detection!=null&&detection.getIfAvailable()!=null)result.addAll(detection.getObject().tasks(actor,1,10,false).items().stream().map(task->new AgentWorkbenchApi.Item(UUID.nameUUIDFromBytes((actor.userId()+":detection:"+task.taskId()).getBytes(StandardCharsets.UTF_8)).toString(),"EXTERNAL_JOB",task.status(),0,Map.<String,Object>of("title","检测任务 "+task.taskId(),"source","DETECTION","resourceId",task.taskId(),"managementPath","/detection","progress",task.processedImages()==null?0:task.processedImages(),"text","通过检测模块读取；取消和重试请在原业务页面执行"),task.createdAt()==null?null:task.createdAt().toString())).toList());
        return List.copyOf(result);
    }
    @Override public List<AgentBusinessFilesApi.Resource> businessFiles(AgentActor actor,String session){assertOwned(actor,session);if(business==null||business.getIfAvailable()==null)return List.of();var result=new ArrayList<AgentBusinessFilesApi.Resource>();for(var reference:store.business(actor.userId(),session,20,false,false))try{result.addAll(business.getObject().list(actor,reference.kind(),reference.resourceId()));}catch(SecurityException|com.ruanzhu.doorhandle.common.BusinessException revoked){/* Omit references whose source permission no longer exists. */}return result;}
    @Override public List<AgentBusinessFilesApi.Resource> attachBusinessFiles(AgentActor actor,String session,String requestId,String kind,String resource){assertOwned(actor,session);request(requestId);if(business==null||business.getIfAvailable()==null)throw fail(409,"业务文件适配未启用");var resources=business.getObject().list(actor,kind,resource);return locked(actor.userId(),()->{
        String signature=hash((session+":"+kind+":"+resource+":ATTACH").getBytes(StandardCharsets.UTF_8));if(store.hasMutation(actor.userId(),requestId,signature))return resources;
        long count=store.businessCount(actor.userId(),session);if(count>=20)throw fail(429,"本会话最多关联 20 个业务对象");
        store.linkBusiness(actor.userId(),session,kind,resource);store.mutation(actor.userId(),requestId,signature);audit(actor,session,resource,"BUSINESS_ATTACHED",signature);return resources;
    });}
    @Override public String fork(AgentActor actor,String session,long through,String requestId){assertOwned(actor,session);request(requestId);return locked(actor.userId(),()->{
        var prior=store.fork(actor.userId(),requestId);if(prior.isPresent()){var row=prior.get();if(!session.equals(row.sourceSessionId())||row.throughMessageId()!=through)throw fail(409,"请求编号已用于其他分支");return row.resultSessionId();}
        var messages=sessions.listMessages(actor.username(),session);int end=-1;for(int i=0;i<messages.size();i++)if(Objects.equals(messages.get(i).getId(),through))end=i;
        if(end<0||!"assistant".equals(messages.get(end).getRole()))throw fail(400,"请选择已结束的助手回复创建分支");
        var child=sessions.createForkSession(actor.username());var tenant=new TenantContext(actor.userId(),actor.username());
        for(var message:messages.subList(0,end+1)){if("user".equals(message.getRole()))sessions.appendUserMessage(tenant,child.getSessionId(),message.getContent());else if("assistant".equals(message.getRole())){
            String text=message.getContent();if(AgentCards.MESSAGE_TYPE.equals(message.getMessageType()))try{text=new ObjectMapper().readValue(text,AgentCards.Envelope.class).text();}catch(Exception error){throw fail(409,"历史消息不可读取");}
            var copied=sessions.appendAssistantMessage(tenant,child.getSessionId(),text,"TEXT","AGENTSCOPE_FORK",null);
            if(turnSnapshots!=null&&turnSnapshots.getIfAvailable()!=null)turnSnapshots.getObject().copy(actor.userId(),session,message.getId(),child.getSessionId(),copied.getId());
        }}
        int bound=jdbc.update("UPDATE chat_session SET fork_owner_user_id=?,fork_request_id=?,fork_source_session_id=?,fork_through_message_id=? WHERE user_id=? AND session_id=? AND fork_request_id IS NULL",actor.userId(),requestId,session,through,actor.userId(),child.getSessionId());
        if(bound!=1)throw fail(409,"分支会话不存在、归属变化或已绑定其他来源");
        store.fork(actor.userId(),requestId,hash((session+":"+through).getBytes(StandardCharsets.UTF_8)),session,through,child.getSessionId());
        boolean exact=turnSnapshots!=null&&turnSnapshots.getIfAvailable()!=null&&turnSnapshots.getObject().inherit(actor.userId(),session,through,child.getSessionId());
        String endedAt=messages.get(end).getCreatedAt();
        if(!exact&&store.hasUnresolvedReferenceClock(actor.userId(),session))throw fail(409,"历史时区未确认，无法确认资料切点，请核对或重新关联资料");
        if(!exact&&endedAt!=null){java.time.LocalDateTime cutoff;try{cutoff=java.time.LocalDateTime.parse(endedAt,java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));}catch(java.time.format.DateTimeParseException error){throw fail(409,"历史时间不可读取，无法确认文件切点");}
            // ChatSessionServiceImpl stores LocalDateTime.now() in the JVM zone; content uses UTC.
            var offsets=java.time.ZoneId.systemDefault().getRules().getValidOffsets(cutoff);
            if(offsets.size()!=1)throw fail(409,"历史消息时间存在时区歧义，无法确认文件切点");
            store.inheritBefore(actor.userId(),session,child.getSessionId(),cutoff.atOffset(offsets.get(0)).withOffsetSameInstant(java.time.ZoneOffset.UTC).toLocalDateTime());
        }
        if(!exact)audit(actor,child.getSessionId(),Long.toString(through),"FORK_LEGACY_FILE_BOUNDARY",hash("仅继承早于旧切点时间的资料；同秒附件需重新关联".getBytes(StandardCharsets.UTF_8)));
        audit(actor,session,child.getSessionId(),"SESSION_FORKED",hash((session+":"+through).getBytes(StandardCharsets.UTF_8)));return child.getSessionId();
    });}
    private static ResponseStatusException fail(int status,String text){return new ResponseStatusException(HttpStatus.valueOf(status),text);}
}
