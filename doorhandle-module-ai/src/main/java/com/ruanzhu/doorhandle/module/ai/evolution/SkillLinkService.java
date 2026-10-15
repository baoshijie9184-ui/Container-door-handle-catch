package com.ruanzhu.doorhandle.module.ai.evolution;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import jakarta.validation.constraints.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import java.nio.file.Path;
import java.net.URI;
import java.util.*;
import java.util.concurrent.*;

/** Durable request, bounded download, immutable package, then existing evaluation/review gates. */
@Service
@ConditionalOnProperty(prefix="agentscope.evolution.links",name="enabled",havingValue="true")
public class SkillLinkService {
    public record Request(@NotBlank @Size(max=1000) String url,@Pattern(regexp="INSPECTOR|SUPERVISOR") @NotNull String targetRole,
            @Pattern(regexp="[A-Za-z0-9_-]{8,64}") @NotNull String requestId,@AssertTrue boolean confirmed){}
    public record UpgradeRequest(@NotBlank @Size(max=1000) String url,@NotNull @Min(1) Integer expectedRevision,
            @Pattern(regexp="[A-Za-z0-9_-]{8,64}") @NotNull String requestId,@AssertTrue boolean confirmed){}
    public record CleanupRequest(@Pattern(regexp="[A-Za-z0-9_-]{8,64}") @NotNull String requestId,@AssertTrue boolean confirmed){}
    public record StorageStatus(long usedBytes,int files,long reservedBytes,long quotaBytes,long availableBytes){}
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final BusinessUserDirectory users;
    private final SkillLinkStorage storage;private final SkillEvolutionService evolution;private final ObjectMapper json;
    private final String python;private final Path installer;
    private final ThreadPoolExecutor jobs=new ThreadPoolExecutor(2,2,0,TimeUnit.SECONDS,new ArrayBlockingQueue<>(8),r->{var t=new Thread(r,"skill-link-download");t.setDaemon(true);return t;});
    private final Set<Process> children=ConcurrentHashMap.newKeySet();
    private final Set<String> liveDownloads=ConcurrentHashMap.newKeySet();
    @Value("${agentscope.evolution.links.quota-bytes:67108864}") private long quotaBytes=67108864L;
    public SkillLinkService(JdbcTemplate jdbc,PlatformTransactionManager manager,BusinessUserDirectory users,SkillLinkStorage storage,
            SkillEvolutionService evolution,ObjectMapper json,@Value("${agentscope.evolution.links.python:python}") String python,
            @Value("${agentscope.evolution.links.installer:${user.dir}/script/shell/download-linked-skill.py}") String installer){
        this.jdbc=jdbc;this.tx=new TransactionTemplate(manager);this.users=users;this.storage=storage;this.evolution=evolution;this.json=json;this.python=python;this.installer=Path.of(installer).toAbsolutePath().normalize();
    }
    @PostConstruct public void schema(){jdbc.queryForList("SELECT download_id,target_skill_id,expected_skill_revision FROM agent_skill_download WHERE 1=0");jdbc.queryForList("SELECT request_id FROM agent_skill_storage_command WHERE 1=0");if(quotaBytes<5242880)throw new IllegalStateException("Skill 存储配额至少为 5 MiB");}
    private AgentActor fresh(AgentActor actor){var current=users.current(actor.userId(),actor.username());return new AgentActor(current.userId(),current.username(),current.supervisor()?AgentActor.Role.SUPERVISOR:AgentActor.Role.INSPECTOR);}
    public Map<String,Object> start(AgentActor actor,Request request){return start(actor,request,null,null);}
    public Map<String,Object> upgrade(AgentActor actor,String skillId,UpgradeRequest request){
        var current=fresh(actor);String role=evolution.linkedUpgradeRole(current,skillId);
        return start(current,new Request(request.url(),role,request.requestId(),request.confirmed()),skillId,request.expectedRevision());
    }
    private synchronized Map<String,Object> start(AgentActor actor,Request request,String targetSkillId,Integer expectedRevision){
        var current=fresh(actor);validateUrl(request.url());
        if(!request.confirmed()||!Set.of("INSPECTOR","SUPERVISOR").contains(request.targetRole())||!request.requestId().matches("[A-Za-z0-9_-]{8,64}"))throw fail(400,"请明确确认下载参数");
        if(!current.supervisor()&&!current.role().name().equals(request.targetRole()))throw fail(403,"员工不能安装主管技能");
        String hash=storage.digest(targetSkillId==null?request:Map.of("request",request,"targetSkillId",targetSkillId,"expectedRevision",expectedRevision)),id="download-"+UUID.randomUUID();
        boolean created=Boolean.TRUE.equals(tx.execute(status->{
            // Lock the owning account's persistent binding row is unnecessary: a unique request index handles concurrent replays.
            var existing=jdbc.queryForList("SELECT request_sha256 FROM agent_skill_download WHERE owner_user_id=? AND request_id=?",current.userId(),request.requestId());
            if(!existing.isEmpty()){if(!hash.equals(existing.get(0).get("request_sha256")))throw fail(409,"请求编号已用于不同的链接下载");return false;}
            if(targetSkillId!=null)evolution.assertLinkedUpgrade(current,targetSkillId,expectedRevision,request.url());
            Long active=jdbc.queryForObject("SELECT COUNT(*) FROM agent_skill_download WHERE owner_user_id=? AND status='DOWNLOADING'",Long.class,current.userId());
            if(active>=2)throw fail(429,"请等待已有下载完成");
            if(storage.usage(current.userId()).bytes()+(active+1)*5242880L>quotaBytes)throw fail(413,"本人 Skill 存储配额不足 请清理未被版本引用的下载缓存");
            jdbc.update("INSERT INTO agent_skill_download(download_id,owner_user_id,request_id,request_sha256,source_url,target_role,target_skill_id,expected_skill_revision,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'DOWNLOADING',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",id,current.userId(),request.requestId(),hash,request.url(),request.targetRole(),targetSkillId,expectedRevision);return true;
        }));
        if(created){try{jobs.execute(()->download(current,id,request));}catch(RejectedExecutionException error){failed(current,id,"DOWNLOAD_QUEUE_FULL");}}
        return jdbc.queryForMap("SELECT download_id,status,skill_id,error_code,created_at,updated_at FROM agent_skill_download WHERE owner_user_id=? AND request_id=?",current.userId(),request.requestId());
    }
    public List<Map<String,Object>> list(AgentActor actor){var current=fresh(actor);return jdbc.queryForList("SELECT download_id,source_url,target_role,target_skill_id,status,skill_id,error_code,created_at,updated_at FROM agent_skill_download WHERE owner_user_id=? ORDER BY id DESC LIMIT 50",current.userId());}
    private void download(AgentActor actor,String id,Request request){Process process=null;
        try{
            if(!Boolean.TRUE.equals(tx.execute(status->{var rows=jdbc.queryForList("SELECT status FROM agent_skill_download WHERE download_id=? AND owner_user_id=? FOR UPDATE",id,actor.userId());
                if(rows.isEmpty()||!"DOWNLOADING".equals(rows.get(0).get("status")))return false;
                jdbc.update("UPDATE agent_skill_download SET updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=?",id,actor.userId());liveDownloads.add(id);return true;})))return;
            Path directory=storage.directory(actor.userId(),id);
            // Do not capture arbitrary installer output, credentials or environment into API error messages.
            process=new ProcessBuilder(python,installer.toString(),"--url",request.url(),"--destination",directory.toString()).redirectOutput(ProcessBuilder.Redirect.DISCARD).redirectError(ProcessBuilder.Redirect.DISCARD).start();children.add(process);
            if(!process.waitFor(180,TimeUnit.SECONDS)){process.destroyForcibly();throw new IllegalStateException("timeout");}
            if(process.exitValue()!=0)throw new IllegalStateException("failed");
            var manifest=storage.inspect(actor.userId(),id);
            if(!request.url().equals(manifest.get("sourceUrl")))throw new IllegalStateException("source mismatch");
            tx.executeWithoutResult(status->{
                int changed=jdbc.update("UPDATE agent_skill_download SET status='DOWNLOADED',manifest_json=?,manifest_sha256=?,updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=? AND status='DOWNLOADING'",write(manifest),storage.digest(manifest),id,actor.userId());
                if(changed!=1)throw fail(409,"下载任务已变化");
                var draft=evolution.createLinked(actor,id,request.targetRole());
                jdbc.update("UPDATE agent_skill_download SET status=CASE WHEN status='NO_CHANGE' THEN status ELSE 'DRAFT_CREATED' END,skill_id=?,updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=?",draft.skillId(),id,actor.userId());
            });
        }catch(Exception error){if(process!=null&&process.isAlive())process.destroyForcibly();if(error instanceof InterruptedException)Thread.currentThread().interrupt();failed(actor,id,"DOWNLOAD_OR_IMPORT_FAILED");}
        finally{if(process!=null)children.remove(process);liveDownloads.remove(id);}
    }
    private void failed(AgentActor actor,String id,String code){jdbc.update("UPDATE agent_skill_download SET status='ERROR',error_code=?,updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=? AND status='DOWNLOADING'",code,id,actor.userId());}
    @org.springframework.scheduling.annotation.Scheduled(fixedDelay=60000) public void expire(){jdbc.update("UPDATE agent_skill_download SET status='ERROR',error_code='DOWNLOAD_LEASE_EXPIRED',updated_at=CURRENT_TIMESTAMP WHERE status='DOWNLOADING' AND updated_at<DATE_SUB(CURRENT_TIMESTAMP,INTERVAL 5 MINUTE)");}
    public StorageStatus storage(AgentActor actor){var current=fresh(actor);var usage=storage.usage(current.userId());long reserved=jdbc.queryForObject("SELECT COUNT(*) FROM agent_skill_download WHERE owner_user_id=? AND status='DOWNLOADING'",Long.class,current.userId())*5242880L;return new StorageStatus(usage.bytes(),usage.files(),reserved,quotaBytes,Math.max(0,quotaBytes-usage.bytes()-reserved));}
    public List<Map<String,Object>> cleanupAudit(AgentActor actor){var current=fresh(actor);return jdbc.queryForList("SELECT request_id,download_id,status,removed_bytes,removed_files,error_code,created_at,updated_at FROM agent_skill_storage_command WHERE owner_user_id=? ORDER BY id DESC LIMIT 50",current.userId());}
    public synchronized Map<String,Object> cleanup(AgentActor actor,String id,CleanupRequest request){
        var current=fresh(actor);if(!request.confirmed())throw fail(400,"请明确确认缓存清理");storage.directory(current.userId(),id);
        String hash=storage.digest(Map.of("downloadId",id,"request",request));
        boolean prepared=Boolean.TRUE.equals(tx.execute(status->{
            var commands=jdbc.queryForList("SELECT request_sha256,status FROM agent_skill_storage_command WHERE owner_user_id=? AND request_id=?",current.userId(),request.requestId());
            boolean resume=!commands.isEmpty();if(resume){if(!hash.equals(commands.get(0).get("request_sha256")))throw fail(409,"请求编号已用于不同清理");if(!"STARTED".equals(commands.get(0).get("status")))return false;}
            var rows=jdbc.queryForList("SELECT status FROM agent_skill_download WHERE download_id=? AND owner_user_id=? FOR UPDATE",id,current.userId());
            if(rows.isEmpty())throw fail(404,"下载记录不存在或无权限");
            if(liveDownloads.contains(id)||!(Set.of("ERROR","NO_CHANGE","DRAFT_CREATED","CLEANUP_ERROR").contains(rows.get(0).get("status"))||resume&&"PURGING".equals(rows.get(0).get("status"))))throw fail(409,"该下载当前不能清理");
            Long references=jdbc.queryForObject("SELECT COUNT(*) FROM agent_skill_version WHERE source_type='LINK' AND source_import_id=?",Long.class,id);
            if(references!=0)throw fail(409,"下载包仍被技能版本引用 请保留审核与回退所需文件");
            if(!resume)jdbc.update("INSERT INTO agent_skill_storage_command(owner_user_id,request_id,request_sha256,download_id,status,created_at,updated_at) VALUES(?,?,?,?,'STARTED',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",current.userId(),request.requestId(),hash,id);
            jdbc.update("UPDATE agent_skill_download SET status='PURGING',updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=?",id,current.userId());return true;
        }));
        if(prepared){try{var removed=storage.purge(current.userId(),id);tx.executeWithoutResult(status->{jdbc.update("UPDATE agent_skill_download SET status='PURGED',updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=? AND status='PURGING'",id,current.userId());jdbc.update("UPDATE agent_skill_storage_command SET status='COMPLETED',removed_bytes=?,removed_files=?,updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_id=?",removed.bytes(),removed.files(),current.userId(),request.requestId());});}
            catch(Exception error){tx.executeWithoutResult(status->{jdbc.update("UPDATE agent_skill_download SET status='CLEANUP_ERROR',updated_at=CURRENT_TIMESTAMP WHERE download_id=? AND owner_user_id=? AND status='PURGING'",id,current.userId());jdbc.update("UPDATE agent_skill_storage_command SET status='ERROR',error_code='CLEANUP_RESULT_UNVERIFIED',updated_at=CURRENT_TIMESTAMP WHERE owner_user_id=? AND request_id=?",current.userId(),request.requestId());});}}
        return jdbc.queryForMap("SELECT request_id,download_id,status,removed_bytes,removed_files,error_code FROM agent_skill_storage_command WHERE owner_user_id=? AND request_id=?",current.userId(),request.requestId());
    }
    public static void validateUrl(String value){
        if("https://modelscope.cn/skills/@anthropics/skill-creator".equals(value)||"https://modelscope.cn/skills/@anthropics/skill-creator/".equals(value))return;
        try{var url=URI.create(value);if(value.length()>1000||!"https".equals(url.getScheme())||!"github.com".equals(url.getRawAuthority())||url.getQuery()!=null||url.getFragment()!=null||!url.getRawPath().matches("/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/tree/[A-Za-z0-9_.-]+/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+/?")||Arrays.stream(url.getPath().split("/")).anyMatch(p->p.equals(".")||p.equals("..")))throw new IllegalArgumentException();}
        catch(Exception error){throw fail(400,"请使用公开 GitHub 的 Skill 目录链接；魔搭目前仅支持已核对的 skill-creator 来源");}
    }
    @PreDestroy public void close(){jobs.shutdownNow();children.forEach(Process::destroyForcibly);}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("技能下载清单编码失败");}}
    private static ResponseStatusException fail(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
