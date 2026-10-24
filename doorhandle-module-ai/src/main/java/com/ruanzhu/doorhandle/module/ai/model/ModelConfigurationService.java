package com.ruanzhu.doorhandle.module.ai.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.config.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import jakarta.annotation.PostConstruct;
import java.util.*;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Immutable, encrypted server snapshots. None of Runtime's properties is an HTTP response type. */
@Service @ConditionalOnProperty(prefix="agentscope.model-config",name="enabled",havingValue="true")
public class ModelConfigurationService implements ModelConfigurationApi {
    public record Option(String id,boolean enabled){}
    public record Document(List<Option> models,String defaultModel,List<String> fallbackModels,boolean fallbackEnabled,
                           long timeoutMs,long firstTokenTimeoutMs,int maxOutputTokens,String memoryModel){}
    public record Draft(long baseRevision,String requestId,Document document,Map<String,String> apiKeys){@Override public String toString(){return "ModelConfigDraft[credentials redacted]";}}
    public record View(long revision,long baseRevision,String status,Document document,Map<String,Boolean> credentials,String memoryState,List<ProbeResult> jsonProbes){}
    public record Runtime(long revision,Document document,AgentModelProperties properties){}
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final BusinessUserDirectory users;private final OperationsAuditApi audit;private final ObjectMapper json;
    private final AgentModelProperties deployed;private final AgentScopeProperties agent;private final ModelConfigCipher cipher;private final String memoryModel;
    private final ObjectProvider<MemoryModelConfigApi> memory;
    private ModelJsonCompatibilityProbe jsonProbe;
    @org.springframework.beans.factory.annotation.Autowired
    public void setJsonProbe(ModelJsonCompatibilityProbe probe){this.jsonProbe=probe;}
    public ModelConfigurationService(JdbcTemplate jdbc,PlatformTransactionManager manager,BusinessUserDirectory users,OperationsAuditApi audit,ObjectMapper json,AgentModelProperties deployed,AgentScopeProperties agent,ObjectProvider<MemoryModelConfigApi> memory,
            @Value("${agentscope.model-config.master-key-file:}") String keyFile,@Value("${MEM0_LLM_MODEL:}") String memoryModel){
        this.jdbc=jdbc;tx=new TransactionTemplate(manager);this.users=users;this.audit=audit;this.json=json;this.deployed=deployed;this.agent=agent;this.memory=memory;this.cipher=new ModelConfigCipher(Path.of(keyFile));this.memoryModel=memoryModel;
    }
    @PostConstruct public void bootstrap(){tx.executeWithoutResult(status->{var control=lock();if(number(control,"active_revision")!=0){runtime(number(control,"active_revision"));verifyStoredEncryption();return;}if(memoryModel==null||memoryModel.isBlank())throw new IllegalStateException("启用模型管理前需提供实际 MEM0_LLM_MODEL，不能猜测现有配置");
        var props=copy(deployed);var configured=new AgentModelService(props,agent);var options=configured.entries().stream().map(model->new Option(model.id(),model.configured())).toList();var fallbacks=configured.fallbackIds();configured.close();
        String memoryId=memoryModel.contains(":")?memoryModel:"dashscope:"+memoryModel;
        var doc=new Document(options,agent.getModel(),fallbacks,props.isFallbackEnabled(),props.getTimeout().toMillis(),props.getFirstTokenTimeout().toMillis(),props.getMaxOutputTokens(),memoryId);validate(doc,props);
        long revision=next(control);insert(revision,0,"PUBLISHED",doc,props,null,"bootstrap",sha(write(doc)));jdbc.update("UPDATE agent_model_configuration SET published_at=CURRENT_TIMESTAMP(6),memory_state='ENVIRONMENT' WHERE revision=?",revision);jdbc.update("UPDATE agent_model_config_control SET active_revision=? WHERE control_id=1",revision);
    });}
    /** Fail at startup when a restored database and Secret do not belong together; never import over existing encrypted history. */
    private void verifyStoredEncryption(){
        long after=0;
        try{
            while(true){
                var rows=jdbc.queryForList("SELECT revision,sealed_snapshot,memory_envelope FROM agent_model_configuration WHERE revision>? ORDER BY revision LIMIT 100",after);
                if(rows.isEmpty())return;
                for(var row:rows){long revision=number(row,"revision");cipher.open("model-config",revision,(String)row.get("sealed_snapshot"));cipher.open("mem0-llm",revision,(String)row.get("memory_envelope"));after=revision;}
            }
        }catch(Exception error){throw new IllegalStateException("模型配置与 Secret 无法核对 请恢复匹配的密钥和数据 拒绝覆盖已有配置");}
    }
    private Map<String,Object> lock(){return jdbc.queryForMap("SELECT * FROM agent_model_config_control WHERE control_id=1 FOR UPDATE");}
    private long next(Map<String,Object> control){long value=number(control,"sequence_value")+1;jdbc.update("UPDATE agent_model_config_control SET sequence_value=? WHERE control_id=1",value);return value;}
    private long number(Map<String,Object> row,String name){return ((Number)row.get(name)).longValue();}
    private AgentActor supervisor(AgentActor actor){var fresh=users.current(actor.userId(),actor.username());if(!fresh.supervisor())throw new SecurityException("仅主管可维护模型配置");return new AgentActor(fresh.userId(),fresh.username(),AgentActor.Role.SUPERVISOR);}
    private void request(String id){if(id==null||!id.matches("[A-Za-z0-9_-]{1,128}"))throw fail(400,"请求编号无效");}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("模型配置编码失败");}}
    private String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException("配置摘要失败");}}
    private AgentModelProperties copy(AgentModelProperties value){return json.convertValue(value,AgentModelProperties.class);}
    private AgentModelProperties.Connection connection(AgentModelProperties p,String provider){return switch(provider){case "dashscope"->p.getDashscope();case "deepseek"->p.getDeepseek();case "openai"->p.getOpenai();default->throw fail(400,"未知接入类型");};}
    private String provider(String id){if(id==null)throw fail(400,"模型编号缺失");if(id.startsWith("dashscope:"))return "dashscope";if(id.startsWith("deepseek:"))return "deepseek";if(id.startsWith("openai-official:"))return "openai";throw fail(400,"只支持现有三类模型接入");}
    private String name(String id){provider(id);String name=id.substring(id.indexOf(':')+1);if(!name.matches("[A-Za-z0-9][A-Za-z0-9._/\\-]{0,127}"))throw fail(400,"模型名称无效");return name;}
    private boolean revoked(String provider,String key){return key!=null&&!key.isBlank()&&jdbc.queryForObject("SELECT COUNT(*) FROM agent_model_revoked_key WHERE provider=? AND key_sha256=?",Long.class,provider,sha(key))>0;}
    private boolean usable(AgentModelProperties p,String provider){var key=connection(p,provider).getApiKey();return key!=null&&!key.isBlank()&&!revoked(provider,key);}
    private void validate(Document d,AgentModelProperties p){
        if(d==null||d.models()==null||d.models().isEmpty()||d.models().size()>48||d.fallbackModels()==null||d.fallbackModels().size()>48||d.timeoutMs()<1000||d.timeoutMs()>3600000||d.firstTokenTimeoutMs()<1000||d.firstTokenTimeoutMs()>d.timeoutMs()||d.maxOutputTokens()<16||d.maxOutputTokens()>65536)throw fail(400,"模型策略参数无效");
        var seen=new HashSet<String>();var enabled=new HashSet<String>();var counts=new HashMap<String,Integer>();
        for(var option:d.models()){if(option==null||!seen.add(option.id()))throw fail(400,"模型重复或无效");String provider=provider(option.id());name(option.id());if(counts.merge(provider,1,Integer::sum)>16)throw fail(400,"每个接入最多 16 个模型");if(option.enabled()){if(!usable(p,provider))throw fail(400,"启用模型需要有效连接凭证");enabled.add(option.id());}}
        if(!enabled.contains(d.defaultModel())||!(d.fallbackEnabled()?enabled:seen).containsAll(d.fallbackModels())||new HashSet<>(d.fallbackModels()).size()!=d.fallbackModels().size())throw fail(400,"默认与备用模型必须已登记，启用备用时须配置有效凭证且不重复");
        if(d.memoryModel()==null||!enabled.contains(d.memoryModel())||provider(d.memoryModel()).equals("openai"))throw fail(400,"提炼模型须使用已启用的 Chat Completions 接入");
    }
    private AgentModelProperties properties(Document d,AgentModelProperties original){var p=copy(original);p.setTimeout(java.time.Duration.ofMillis(d.timeoutMs()));p.setFirstTokenTimeout(java.time.Duration.ofMillis(d.firstTokenTimeoutMs()));p.setMaxOutputTokens(d.maxOutputTokens());p.setFallbackEnabled(d.fallbackEnabled());p.setFallbackModels(d.fallbackModels());p.setAdditionalFallbackModels(List.of());
        for(String provider:List.of("dashscope","deepseek","openai")){var names=d.models().stream().filter(option->provider(option.id()).equals(provider)).map(option->name(option.id())).toList();if(!names.isEmpty()){connection(p,provider).setModel(names.get(0));connection(p,provider).setAdditionalModels(names.subList(1,names.size()));}}
        return p;
    }
    private void insert(long revision,long base,String status,Document doc,AgentModelProperties properties,Long creator,String request,String digest){String sealed=cipher.seal("model-config",revision,write(Map.of("properties",properties,"document",doc)));var memoryConnection=connection(properties,provider(doc.memoryModel()));String memoryEnvelope=cipher.seal("mem0-llm",revision,write(Map.of("provider",provider(doc.memoryModel()),"model",name(doc.memoryModel()),"api_key",memoryConnection.getApiKey(),"base_url",memoryConnection.getBaseUrl())));jdbc.update("INSERT INTO agent_model_configuration(revision,base_revision,status,document_json,sealed_snapshot,memory_envelope,creator_user_id,request_id,request_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",revision,base,status,write(doc),sealed,memoryEnvelope,creator,request,digest);}
    private Map<String,Object> row(long revision){var rows=jdbc.queryForList("SELECT * FROM agent_model_configuration WHERE revision=?",revision);if(rows.isEmpty())throw fail(404,"模型配置不存在");return rows.get(0);}
    public Runtime runtime(long revision){var row=row(revision);try{var node=json.readTree(cipher.open("model-config",revision,(String)row.get("sealed_snapshot")));return new Runtime(revision,json.treeToValue(node.get("document"),Document.class),json.treeToValue(node.get("properties"),AgentModelProperties.class));}catch(ResponseStatusException error){throw error;}catch(Exception error){throw new IllegalStateException("模型配置不能安全加载");}}
    public void assertUsable(long revision,String id){var r=runtime(revision);var status=row(revision).get("status");if(!Set.of("PUBLISHED","RETIRED").contains(status)||r.document().models().stream().noneMatch(option->option.enabled()&&option.id().equals(id))||!usable(r.properties(),provider(id)))throw fail(409,"任务引用的模型版本或凭证已不可用，请重新选择模型");}
    public Set<String> enabledIds(long revision){var r=runtime(revision);var providers=new HashSet<String>();for(String provider:List.of("dashscope","deepseek","openai"))if(usable(r.properties(),provider))providers.add(provider);return r.document().models().stream().filter(option->option.enabled()&&providers.contains(provider(option.id()))).map(Option::id).collect(java.util.stream.Collectors.toSet());}
    @Override public Active active(){long revision=jdbc.queryForObject("SELECT active_revision FROM agent_model_config_control WHERE control_id=1",Long.class);var r=runtime(revision);return new Active(revision,r.document().defaultModel(),r.document().memoryModel());}
    @Override public void assertTaskConfiguration(long revision,String modelId){if(revision<1)throw fail(409,"原任务没有固定模型配置，请选择当前可用配置后再恢复");assertUsable(revision,modelId);}
    public View get(AgentActor actor,long revision){supervisor(actor);return view(revision);}
    private View view(long revision){var row=row(revision);var r=runtime(revision);var credentials=new LinkedHashMap<String,Boolean>();for(String provider:List.of("dashscope","deepseek","openai"))credentials.put(provider,usable(r.properties(),provider));var probes=jdbc.queryForList("SELECT model_id,request_id,status FROM agent_model_json_probe WHERE revision=? ORDER BY created_at DESC LIMIT 50",revision).stream().map(probe->new ProbeResult(revision,(String)probe.get("model_id"),(String)probe.get("request_id"),(String)probe.get("status"))).toList();return new View(revision,number(row,"base_revision"),(String)row.get("status"),r.document(),credentials,(String)row.get("memory_state"),probes);}
    public List<View> list(AgentActor actor){supervisor(actor);var result=new ArrayList<>(jdbc.queryForList("SELECT revision FROM agent_model_configuration ORDER BY revision DESC LIMIT 30").stream().map(row->view(number(row,"revision"))).toList());long active=active().version();if(result.stream().noneMatch(view->view.revision()==active))result.add(view(active));return List.copyOf(result);}
    public View draft(AgentActor actor,Draft input){var current=supervisor(actor);if(input==null||input.document()==null)throw fail(400,"模型配置缺失");request(input.requestId());return tx.execute(status->{var control=lock();var keys=input.apiKeys()==null?Map.<String,String>of():input.apiKeys();for(var entry:keys.entrySet())if(!Set.of("dashscope","deepseek","openai").contains(entry.getKey())||entry.getValue()==null||entry.getValue().isBlank()||entry.getValue().length()>4096||entry.getValue().chars().anyMatch(Character::isISOControl))throw fail(400,"连接凭证格式无效");
        String digest=sha(write(Map.of("base",input.baseRevision(),"document",input.document(),"keyDigests",keys.entrySet().stream().collect(java.util.stream.Collectors.toMap(Map.Entry::getKey,e->sha(e.getValue()))))));
        var previous=jdbc.queryForList("SELECT revision,request_sha256 FROM agent_model_configuration WHERE creator_user_id=? AND request_id=?",current.userId(),input.requestId());if(!previous.isEmpty()){if(!digest.equals(previous.get(0).get("request_sha256")))throw fail(409,"请求编号用于其他配置");return view(number(previous.get(0),"revision"));}
        if(number(control,"active_revision")!=input.baseRevision())throw fail(409,"生效版本已变化，请刷新");var base=runtime(input.baseRevision());var p=properties(input.document(),base.properties());keys.forEach((provider,key)->connection(p,provider).setApiKey(key));validate(input.document(),p);long revision=next(control);insert(revision,input.baseRevision(),"DRAFT",input.document(),p,current.userId(),input.requestId(),digest);audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","MODEL_CONFIG","DRAFT",Long.toString(revision),input.requestId(),"SAVED",revision));return view(revision);
    });}
    private Long receipt(AgentActor actor,String request,String action,String target){
        var rows=jdbc.queryForList("SELECT action,target,revision FROM agent_model_config_command WHERE actor_user_id=? AND request_id=?",actor.userId(),request);
        if(rows.isEmpty())return null;
        var previous=rows.get(0);
        if(!action.equals(previous.get("action"))||!target.equals(previous.get("target")))throw fail(409,"请求编号已用于其他模型操作");
        return number(previous,"revision");
    }
    private void receipt(AgentActor actor,String request,String action,String target,long revision){
        jdbc.update("INSERT INTO agent_model_config_command(actor_user_id,request_id,action,target,revision,created_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP(6))",actor.userId(),request,action,target,revision);
    }
    public View validate(AgentActor actor,long revision,String request){var current=supervisor(actor);request(request);return tx.execute(status->{var control=lock();var previous=receipt(current,request,"VALIDATE",Long.toString(revision));if(previous!=null)return view(previous);var row=row(revision);if(!Set.of("DRAFT","VALIDATED").contains(row.get("status")))throw fail(409,"配置不在草稿状态");if(number(control,"active_revision")!=number(row,"base_revision"))throw fail(409,"生效版本已变化，请重新创建草稿");var r=runtime(revision);validate(r.document(),r.properties());var old=runtime(number(row,"base_revision"));
        boolean changed=!old.document().memoryModel().equals(r.document().memoryModel())||!Objects.equals(connection(old.properties(),provider(old.document().memoryModel())).getApiKey(),connection(r.properties(),provider(r.document().memoryModel())).getApiKey());
        if(changed&&jdbc.queryForObject("SELECT COUNT(*) FROM agent_model_json_probe WHERE revision=? AND model_id=? AND status='PASSED'",Long.class,revision,r.document().memoryModel())==0)throw fail(409,"新的提炼连接须先通过一次 JSON 兼容检查");
        jdbc.update("UPDATE agent_model_configuration SET status='VALIDATED' WHERE revision=?",revision);receipt(current,request,"VALIDATE",Long.toString(revision),revision);audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","MODEL_CONFIG","VALIDATE",Long.toString(revision),request,"PASSED",revision));return view(revision);
    });}
    public record ProbeResult(long revision,String modelId,String requestId,String status){}
    public ProbeResult probeJson(AgentActor actor,long revision,String modelId,String requestId){
        var current=supervisor(actor);request(requestId);
        if(jsonProbe==null)throw fail(503,"JSON 检查未启用");
        boolean started=Boolean.TRUE.equals(tx.execute(status->{
            var control=lock();var stored=row(revision);
            var previous=jdbc.queryForList("SELECT model_id,status FROM agent_model_json_probe WHERE revision=? AND request_id=?",revision,requestId);
            if(!previous.isEmpty()){
                if(!Objects.equals(previous.get(0).get("model_id"),modelId))throw fail(409,"检查请求编号已用于其他模型");
                return false;
            }
            if(!"DRAFT".equals(stored.get("status"))||number(control,"active_revision")!=number(stored,"base_revision"))throw fail(409,"请对当前版本的草稿执行检查");
            var snapshot=runtime(revision);validate(snapshot.document(),snapshot.properties());
            if(!Objects.equals(snapshot.document().memoryModel(),modelId))throw fail(400,"仅检查此草稿的提炼候选模型");
            jdbc.update("INSERT INTO agent_model_json_probe(revision,model_id,request_id,status,created_at) VALUES(?,?,?,'STARTED',CURRENT_TIMESTAMP(6))",revision,modelId,requestId);
            audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","MODEL_CONFIG","JSON_PROBE",Long.toString(revision),requestId,"STARTED",revision));
            return true;
        }));
        if(started){
            boolean passed=jsonProbe.check(runtime(revision),modelId);
            tx.executeWithoutResult(status->{lock();
                // Reauthenticate before making this result available for validation.
                var fresh=supervisor(current);
                jdbc.update("UPDATE agent_model_json_probe SET status=? WHERE revision=? AND request_id=? AND status='STARTED'",passed?"PASSED":"FAILED",revision,requestId);
                audit.append(new OperationsAuditApi.Event(fresh,"ENTERPRISE","MODEL_CONFIG","JSON_PROBE",Long.toString(revision),requestId,passed?"PASSED":"FAILED",revision));
            });
        }
        return new ProbeResult(revision,modelId,requestId,jdbc.queryForObject("SELECT status FROM agent_model_json_probe WHERE revision=? AND request_id=?",String.class,revision,requestId));
    }
    public View publish(AgentActor actor,long revision,String request){var current=supervisor(actor);request(request);
        var completed=tx.execute(status->{lock();return receipt(current,request,"PUBLISH",Long.toString(revision));});
        if(completed!=null)return view(completed);
        var r=runtime(revision);validate(r.document(),r.properties());var bridge=memory.getIfAvailable();if(bridge==null)throw fail(503,"记忆配置桥接未启用，未发布新版本");
        var candidate=row(revision);if(!Set.of("VALIDATED","PUBLISHED").contains(candidate.get("status")))throw fail(409,"配置尚未校验，未提交记忆应用");bridge.prepare(revision,(String)candidate.get("memory_envelope"));
        tx.executeWithoutResult(status->{supervisor(current);var control=lock();if(receipt(current,request,"PUBLISH",Long.toString(revision))!=null)return;var stored=row(revision);if(number(control,"active_revision")==revision&&"PUBLISHED".equals(stored.get("status"))){receipt(current,request,"PUBLISH",Long.toString(revision),revision);return;}if(!"VALIDATED".equals(stored.get("status"))||number(control,"active_revision")!=number(stored,"base_revision"))throw fail(409,"配置状态或当前版本已变化");
            jdbc.update("UPDATE agent_model_configuration SET status='RETIRED' WHERE revision=?",number(control,"active_revision"));jdbc.update("UPDATE agent_model_configuration SET status='PUBLISHED',memory_state='PENDING',published_at=CURRENT_TIMESTAMP(6) WHERE revision=?",revision);jdbc.update("UPDATE agent_model_config_control SET active_revision=? WHERE control_id=1",revision);receipt(current,request,"PUBLISH",Long.toString(revision),revision);audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","MODEL_CONFIG","PUBLISH",Long.toString(revision),request,"APPLIED",revision));});
        reconcileMemory();return view(revision);
    }
    /** Idempotent metadata reconciliation only; never generates memories or retries an LLM write. */
    @org.springframework.scheduling.annotation.Scheduled(fixedDelay=10000)
    public void reconcileMemory(){
        var bridge=memory.getIfAvailable();if(bridge==null)return;
        try{
            for(var key:jdbc.queryForList("SELECT provider,key_sha256 FROM agent_model_revoked_key WHERE memory_propagated=FALSE")){
                bridge.revokeCredential((String)key.get("key_sha256"));
                jdbc.update("UPDATE agent_model_revoked_key SET memory_propagated=TRUE WHERE provider=? AND key_sha256=?",key.get("provider"),key.get("key_sha256"));
            }
            var current=active();var stored=row(current.version());
            if(!"PENDING".equals(stored.get("memory_state")))return;
            var snapshot=runtime(current.version());
            if(!usable(snapshot.properties(),provider(snapshot.document().memoryModel())))return;
            if(bridge.appliedRevision()!=current.version())bridge.apply(current.version());
            if(bridge.appliedRevision()==current.version())jdbc.update("UPDATE agent_model_configuration SET memory_state='APPLIED' WHERE revision=? AND status='PUBLISHED'",current.version());
        }catch(RuntimeException ignored){/* Metadata stays pending. No extraction, credentials or exception bodies are logged. */}
    }
    @Override public void assertMemoryAvailable(){
        var current=active();var stored=row(current.version());var snapshot=runtime(current.version());
        if(!Set.of("ENVIRONMENT","APPLIED").contains(stored.get("memory_state"))||!usable(snapshot.properties(),provider(snapshot.document().memoryModel())))
            throw fail(503,"记忆提炼模型配置尚未应用或凭证已撤销，本次不会开始提炼");
    }
    public View restore(AgentActor actor,long revision,long base,String request){supervisor(actor);var old=runtime(revision);return draft(actor,new Draft(base,request,old.document(),Map.of()));}
    public void revoke(AgentActor actor,String provider,long revision,String request){var current=supervisor(actor);request(request);tx.executeWithoutResult(status->{var control=lock();String target=provider+":"+revision;if(receipt(current,request,"REVOKE_KEY",target)!=null)return;if(number(control,"active_revision")!=revision)throw fail(409,"生效版本已变化，请重新核对凭证");var key=connection(runtime(revision).properties(),provider).getApiKey();if(key==null||key.isBlank())throw fail(409,"此接入没有可撤销的凭证");if(!revoked(provider,key))jdbc.update("INSERT INTO agent_model_revoked_key(provider,key_sha256,actor_user_id,request_id,created_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP(6))",provider,sha(key),current.userId(),request);receipt(current,request,"REVOKE_KEY",target,revision);audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","MODEL_CONFIG","REVOKE_KEY",provider,request,"APPLIED",revision));});reconcileMemory();}
    public static ResponseStatusException fail(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
