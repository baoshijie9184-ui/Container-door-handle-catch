package com.ruanzhu.doorhandle.module.app.service.impl;

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
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final Path root;private final long maxBytes,quotaBytes;
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
        this.sessions=sessions;this.users=users;this.inbox=inbox;this.jdbc=jdbc;tx=new TransactionTemplate(manager);tx.setTimeout(5);this.root=Path.of(root).toAbsolutePath().normalize();this.maxBytes=maxBytes;this.quotaBytes=quotaBytes;
    }
    @PostConstruct public void validate(){jdbc.queryForList("SELECT file_id FROM agent_workspace_file WHERE 1=0");jdbc.queryForList("SELECT request_id FROM agent_session_fork WHERE 1=0");if(maxBytes<1||quotaBytes<maxBytes||previewBytes<1||previewBytes>1048576)throw new IllegalStateException("文件配额或预览配置无效");}
    public Map<String,Long> limits(){return Map.of("maxFileBytes",maxBytes,"quotaBytes",quotaBytes,"previewBytes",(long)previewBytes);}
    @Override public void assertOwned(AgentActor actor,String session){var current=users.current(actor.userId(),actor.username());if(current.userId()!=actor.userId()||current.supervisor()!=actor.supervisor())throw new SecurityException("账号身份已变化");if(sessions.resolveTenantForSystemCallback(session).userId()!=actor.userId())throw fail(404,"会话不存在或无权限");sessions.verifySessionOwner(actor.username(),session);}
    private <T>T locked(long user,Supplier<T> work){return tx.execute(status->{jdbc.update("INSERT INTO agent_workspace_owner(user_id) VALUES(?) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id)",user);jdbc.queryForObject("SELECT user_id FROM agent_workspace_owner WHERE user_id=? FOR UPDATE",Long.class,user);return work.get();});}
    private static String hash(byte[] data){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));}catch(Exception error){throw new IllegalStateException(error);}}
    private static void request(String id){if(id==null||!id.matches("[A-Za-z0-9_-]{1,128}"))throw fail(400,"请求编号无效");}
    private void audit(AgentActor actor,String session,String resource,String action,String digest){jdbc.update("INSERT INTO agent_workspace_audit(user_id,session_id,resource_id,action,content_sha256) VALUES(?,?,?,?,?)",actor.userId(),session,resource,action,digest);}
    private File file(Map<String,Object> row){return new File((String)row.get("file_id"),(String)row.get("filename"),(String)row.get("content_type"),((Number)row.get("byte_length")).longValue(),(String)row.get("sha256"),(String)row.get("folder"));}
    @Override public List<File> files(AgentActor actor,String session){assertOwned(actor,session);return jdbc.queryForList("SELECT f.* FROM agent_workspace_file f JOIN agent_workspace_file_ref r ON r.file_id=f.file_id AND r.user_id=f.user_id WHERE r.user_id=? AND r.session_id=? ORDER BY f.id DESC LIMIT 200",actor.userId(),session).stream().map(this::file).toList();}
    public File requireFile(AgentActor actor,String session,String id){assertOwned(actor,session);var found=jdbc.queryForList("SELECT f.* FROM agent_workspace_file f JOIN agent_workspace_file_ref r ON r.file_id=f.file_id AND r.user_id=f.user_id WHERE r.user_id=? AND r.session_id=? AND f.file_id=?",actor.userId(),session,id);if(found.size()!=1)throw fail(404,"文件不存在或无权限");return file(found.get(0));}
    public void requireBusinessReference(AgentActor actor,String session,String kind,String resource){assertOwned(actor,session);if(!"DETECTION".equals(kind)||resource==null||!resource.matches("[A-Za-z0-9_-]{1,128}"))throw fail(400,"检测业务引用无效");if(jdbc.queryForObject("SELECT COUNT(*) FROM agent_workspace_business_ref WHERE user_id=? AND session_id=? AND kind=? AND resource_id=?",Integer.class,actor.userId(),session,kind,resource)!=1)throw fail(403,"请先将有权访问的检测任务关联到当前会话");}
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
            var old=jdbc.queryForList("SELECT * FROM agent_workspace_file WHERE user_id=? AND request_id=?",actor.userId(),requestId);
            if(!old.isEmpty()){var prior=file(old.get(0));if(!prior.sha256().equals(digest)||!prior.name().equals(name)||!prior.folder().equals(folder)||jdbc.queryForObject("SELECT COUNT(*) FROM agent_workspace_file_ref WHERE user_id=? AND session_id=? AND file_id=?",Integer.class,actor.userId(),session,prior.id())!=1)throw fail(409,"请求编号已使用");return prior;}
            long used=jdbc.queryForObject("SELECT COALESCE(SUM(byte_length),0) FROM agent_workspace_file WHERE user_id=?",Long.class,actor.userId());if(used+bytes.length>quotaBytes)throw fail(413,"本人文件存储配额不足");
            String id=UUID.randomUUID().toString();Path target=location(actor.userId(),id,true);
            try{Files.write(target,bytes,StandardOpenOption.CREATE_NEW);}catch(java.io.IOException error){throw fail(503,"文件保存失败");}
            org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(new org.springframework.transaction.support.TransactionSynchronization(){@Override public void afterCompletion(int status){if(status!=STATUS_COMMITTED)try{Files.deleteIfExists(target);}catch(java.io.IOException ignored){}}});
            try{jdbc.update("INSERT INTO agent_workspace_file(file_id,user_id,request_id,filename,content_type,byte_length,sha256,folder) VALUES(?,?,?,?,?,?,?,?)",id,actor.userId(),requestId,name,contentType,bytes.length,digest,folder);jdbc.update("INSERT INTO agent_workspace_file_ref(user_id,session_id,file_id) VALUES(?,?,?)",actor.userId(),session,id);audit(actor,session,id,"FILE_CREATED",digest);}
            catch(RuntimeException error){try{Files.deleteIfExists(target);}catch(java.io.IOException ignored){}throw error;}
            return new File(id,name,contentType,bytes.length,digest,folder);
        });
    }
    @Override public File createArtifact(AgentActor actor,String session,String requestId,String name,String content){assertOwned(actor,session);if(name==null||!List.of(".md",".csv",".json").stream().anyMatch(name.toLowerCase(Locale.ROOT)::endsWith)||content==null||content.length()>500000)throw fail(400,"产物名称或内容无效");if(name.toLowerCase(Locale.ROOT).endsWith(".json"))WorkspaceFileContent.validateJson(content,400);return upload(actor,session,requestId,name,content.getBytes(StandardCharsets.UTF_8),"artifacts");}
    public byte[] bytes(AgentActor actor,String session,String id){var metadata=requireFile(actor,session,id);if("context".equals(metadata.folder())){if(contextAccess==null||contextAccess.getIfAvailable()==null)throw fail(503,"上下文资料的权限核对服务未启用");contextAccess.getObject().assertReadable(actor,session,id);}return bytesForContextValidation(actor,session,id);}
    byte[] bytesForContextValidation(AgentActor actor,String session,String id){var metadata=requireFile(actor,session,id);try{Path path=location(actor.userId(),id,false);if(Files.size(path)!=metadata.bytes()||Files.size(path)>maxBytes)throw fail(409,"文件长度已变化");byte[] data=Files.readAllBytes(path);if(!hash(data).equals(metadata.sha256()))throw fail(409,"文件摘要已变化");return data;}catch(java.io.IOException error){throw fail(404,"文件内容不可用");}}
    @Override public String readText(AgentActor actor,String session,String id){var metadata=requireFile(actor,session,id);if("context".equals(metadata.folder()))throw fail(403,"上下文卸载资料请通过当前 Agent 的 read_context_file 受控读取");byte[] data=bytes(actor,session,id);return WorkspaceFileContent.read(metadata.contentType(),data,previewBytes);}
    public record PdfPreview(byte[] png,int page,int pages){}
    public PdfPreview previewPdf(AgentActor actor,String session,String id,int page){var metadata=requireFile(actor,session,id);if(!metadata.contentType().equals("application/pdf"))throw fail(415,"此预览接口仅用于 PDF");var result=WorkspaceFileContent.previewPdf(bytes(actor,session,id),page);return new PdfPreview(result.png(),result.page(),result.pages());}
    public void remove(AgentActor actor,String session,String id,String requestId){assertOwned(actor,session);request(requestId);locked(actor.userId(),()->{
        String signature=hash((session+":"+id+":REMOVE").getBytes(StandardCharsets.UTF_8));var old=jdbc.queryForList("SELECT signature FROM agent_workspace_request WHERE user_id=? AND request_id=?",actor.userId(),requestId);
        if(!old.isEmpty()){if(!signature.equals(old.get(0).get("signature")))throw fail(409,"请求编号已使用");return null;}
        var metadata=requireFile(actor,session,id);if("context".equals(metadata.folder()))throw fail(409,"上下文资料仍被执行记录引用，暂不能移除");jdbc.update("DELETE FROM agent_workspace_file_ref WHERE user_id=? AND session_id=? AND file_id=?",actor.userId(),session,id);audit(actor,session,id,"FILE_UNLINKED",metadata.sha256());
        jdbc.update("INSERT INTO agent_workspace_request(user_id,request_id,signature) VALUES(?,?,?)",actor.userId(),requestId,signature);return null;
    });}
    @Override public void continueSession(AgentActor actor,String session,String requestId,String content){assertOwned(actor,session);inbox.getObject().enqueue(actor,session,requestId,"NEXT_TURN",content,"CHAT");}
    public Map<String,Object> lineage(AgentActor actor,String session){assertOwned(actor,session);var rows=jdbc.queryForList("SELECT source_session_id,through_message_id FROM agent_session_fork WHERE user_id=? AND fork_session_id=?",actor.userId(),session);if(rows.isEmpty())return Map.of();boolean legacy=jdbc.queryForObject("SELECT COUNT(*) FROM agent_workspace_audit WHERE user_id=? AND session_id=? AND action='FORK_LEGACY_FILE_BOUNDARY'",Long.class,actor.userId(),session)>0;return Map.of("sourceSessionId",rows.get(0).get("source_session_id"),"throughMessageId",rows.get(0).get("through_message_id"),"legacyFileBoundary",legacy);}
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
    @Override public List<AgentBusinessFilesApi.Resource> businessFiles(AgentActor actor,String session){assertOwned(actor,session);if(business==null||business.getIfAvailable()==null)return List.of();var result=new ArrayList<AgentBusinessFilesApi.Resource>();for(var reference:jdbc.queryForList("SELECT kind,resource_id FROM agent_workspace_business_ref WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT 20",actor.userId(),session))try{result.addAll(business.getObject().list(actor,(String)reference.get("kind"),(String)reference.get("resource_id")));}catch(SecurityException|com.ruanzhu.doorhandle.common.BusinessException revoked){/* Omit references whose source permission no longer exists. */}return result;}
    @Override public List<AgentBusinessFilesApi.Resource> attachBusinessFiles(AgentActor actor,String session,String requestId,String kind,String resource){assertOwned(actor,session);request(requestId);if(business==null||business.getIfAvailable()==null)throw fail(409,"业务文件适配未启用");var resources=business.getObject().list(actor,kind,resource);return locked(actor.userId(),()->{
        String signature=hash((session+":"+kind+":"+resource+":ATTACH").getBytes(StandardCharsets.UTF_8));var old=jdbc.queryForList("SELECT signature FROM agent_workspace_request WHERE user_id=? AND request_id=?",actor.userId(),requestId);if(!old.isEmpty()){if(!signature.equals(old.get(0).get("signature")))throw fail(409,"请求编号已使用");return resources;}
        long count=jdbc.queryForObject("SELECT COUNT(*) FROM agent_workspace_business_ref WHERE user_id=? AND session_id=?",Long.class,actor.userId(),session);if(count>=20)throw fail(429,"本会话最多关联 20 个业务对象");
        jdbc.update("INSERT INTO agent_workspace_business_ref(user_id,session_id,kind,resource_id) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE resource_id=VALUES(resource_id)",actor.userId(),session,kind,resource);jdbc.update("INSERT INTO agent_workspace_request(user_id,request_id,signature) VALUES(?,?,?)",actor.userId(),requestId,signature);audit(actor,session,resource,"BUSINESS_ATTACHED",signature);return resources;
    });}
    @Override public String fork(AgentActor actor,String session,long through,String requestId){assertOwned(actor,session);request(requestId);return locked(actor.userId(),()->{
        var prior=jdbc.queryForList("SELECT * FROM agent_session_fork WHERE user_id=? AND request_id=?",actor.userId(),requestId);if(!prior.isEmpty()){var row=prior.get(0);if(!session.equals(row.get("source_session_id"))||((Number)row.get("through_message_id")).longValue()!=through)throw fail(409,"请求编号已用于其他分支");return (String)row.get("fork_session_id");}
        var messages=sessions.listMessages(actor.username(),session);int end=-1;for(int i=0;i<messages.size();i++)if(Objects.equals(messages.get(i).getId(),through))end=i;
        if(end<0||!"assistant".equals(messages.get(end).getRole()))throw fail(400,"请选择已结束的助手回复创建分支");
        var child=sessions.createForkSession(actor.username());var tenant=new TenantContext(actor.userId(),actor.username());
        for(var message:messages.subList(0,end+1)){if("user".equals(message.getRole()))sessions.appendUserMessage(tenant,child.getSessionId(),message.getContent());else if("assistant".equals(message.getRole())){
            String text=message.getContent();if(AgentCards.MESSAGE_TYPE.equals(message.getMessageType()))try{text=new ObjectMapper().readValue(text,AgentCards.Envelope.class).text();}catch(Exception error){throw fail(409,"历史消息不可读取");}
            var copied=sessions.appendAssistantMessage(tenant,child.getSessionId(),text,"TEXT","AGENTSCOPE_FORK",null);
            if(turnSnapshots!=null&&turnSnapshots.getIfAvailable()!=null)turnSnapshots.getObject().copy(actor.userId(),session,message.getId(),child.getSessionId(),copied.getId());
        }}
        jdbc.update("INSERT INTO agent_session_fork(user_id,request_id,source_session_id,through_message_id,fork_session_id) VALUES(?,?,?,?,?)",actor.userId(),requestId,session,through,child.getSessionId());
        boolean exact=turnSnapshots!=null&&turnSnapshots.getIfAvailable()!=null&&turnSnapshots.getObject().inherit(actor.userId(),session,through,child.getSessionId());
        String endedAt=messages.get(end).getCreatedAt();
        if(!exact&&endedAt!=null){java.time.LocalDateTime cutoff;try{cutoff=java.time.LocalDateTime.parse(endedAt,java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));}catch(java.time.format.DateTimeParseException error){throw fail(409,"历史时间不可读取，无法确认文件切点");}
            jdbc.update("INSERT INTO agent_workspace_file_ref(user_id,session_id,file_id) SELECT user_id,?,file_id FROM agent_workspace_file_ref WHERE user_id=? AND session_id=? AND created_at<?",child.getSessionId(),actor.userId(),session,cutoff);
            jdbc.update("INSERT INTO agent_workspace_business_ref(user_id,session_id,kind,resource_id) SELECT user_id,?,kind,resource_id FROM agent_workspace_business_ref WHERE user_id=? AND session_id=? AND created_at<?",child.getSessionId(),actor.userId(),session,cutoff);
        }
        if(!exact)audit(actor,child.getSessionId(),Long.toString(through),"FORK_LEGACY_FILE_BOUNDARY",hash("仅继承早于旧切点时间的资料；同秒附件需重新关联".getBytes(StandardCharsets.UTF_8)));
        audit(actor,session,child.getSessionId(),"SESSION_FORKED",hash((session+":"+through).getBytes(StandardCharsets.UTF_8)));return child.getSessionId();
    });}
    private static ResponseStatusException fail(int status,String text){return new ResponseStatusException(HttpStatus.valueOf(status),text);}
}
