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
    public record View(long revision,long baseRevision,String status,Document document,Map<String,Boolean> credentials,String memoryState,List<ProbeResult> jsonProbes,String changeVersion){
        public View(long revision,long baseRevision,String status,Document document,Map<String,Boolean> credentials,String memoryState,List<ProbeResult> jsonProbes){this(revision,baseRevision,status,document,credentials,memoryState,jsonProbes,null);}
    }
    public record Runtime(long revision,Document document,AgentModelProperties properties){}
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final BusinessUserDirectory users;private final OperationsAuditApi audit;private final ObjectMapper json;
    private final AgentModelProperties deployed;private final AgentScopeProperties agent;private final ModelConfigCipher cipher;private final String memoryModel;
    private final ObjectProvider<MemoryModelConfigApi> memory;
    private ModelJsonCompatibilityProbe jsonProbe;
    private final ModelConfigurationStore store;
    private AiCollaborationHistory collaborationHistory;
    @Value("${collaboration.change-history.enabled:false}") private boolean requireHistory;
    @Value("${collaboration.mutations.enabled:false}") private boolean requireCommands;
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    public void collaborationHistory(AiCollaborationHistory history){this.collaborationHistory=history;}
    private boolean collaboration(){return collaborationHistory!=null&&collaborationHistory.enabled();}
    private boolean protectedCommands(){return collaborationHistory!=null&&collaborationHistory.protectsCommands();}
    @org.springframework.beans.factory.annotation.Autowired
    public void setJsonProbe(ModelJsonCompatibilityProbe probe){this.jsonProbe=probe;}
    public ModelConfigurationService(JdbcTemplate jdbc,PlatformTransactionManager manager,BusinessUserDirectory users,OperationsAuditApi audit,ObjectMapper json,AgentModelProperties deployed,AgentScopeProperties agent,ObjectProvider<MemoryModelConfigApi> memory,
            @Value("${agentscope.model-config.master-key-file:}") String keyFile,@Value("${MEM0_LLM_MODEL:}") String memoryModel){
        this.jdbc=jdbc;tx=new TransactionTemplate(manager);
        // Configuration commands serialize on the singleton; reads after waiting for it
        // must see the committed winner rather than an earlier MySQL RR snapshot.
        tx.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_READ_COMMITTED);
        this.users=users;this.audit=audit;this.json=json;this.deployed=deployed;this.agent=agent;this.memory=memory;this.cipher=new ModelConfigCipher(Path.of(keyFile));this.memoryModel=memoryModel;this.store=new ModelConfigurationStore(jdbc,json);
    }
    @PostConstruct public void bootstrap(){if((requireHistory||requireCommands)&&collaborationHistory==null)throw new IllegalStateException("AI collaboration history component required");tx.executeWithoutResult(status->{var control=lock();if(number(control,"active_revision")!=0){runtime(number(control,"active_revision"));verifyStoredEncryption();return;}if(memoryModel==null||memoryModel.isBlank())throw new IllegalStateException("启用模型管理前需提供实际 MEM0_LLM_MODEL，不能猜测现有配置");
        var props=copy(deployed);var configured=new AgentModelService(props,agent);var options=configured.entries().stream().map(model->new Option(model.id(),model.configured())).toList();var fallbacks=configured.fallbackIds();configured.close();
        String memoryId=memoryModel.contains(":")?memoryModel:"dashscope:"+memoryModel;
        var doc=new Document(options,agent.getModel(),fallbacks,props.isFallbackEnabled(),props.getTimeout().toMillis(),props.getFirstTokenTimeout().toMillis(),props.getMaxOutputTokens(),memoryId);validate(doc,props);
        long revision=next(control);insert(revision,0,"PUBLISHED",doc,props,null,"bootstrap",sha(write(doc)));jdbc.update("UPDATE llm_configuration SET published_at=UTC_TIMESTAMP(6),memory_state='ENVIRONMENT' WHERE revision=?",revision);store.activate(revision);
    });}
    /** Fail at startup when a restored database and Secret do not belong together; never import over existing encrypted history. */
    private void verifyStoredEncryption(){
        long after=0;
        try{
            while(true){
                var rows=jdbc.queryForList("SELECT revision,sealed_snapshot,memory_envelope FROM llm_configuration WHERE revision>? ORDER BY revision LIMIT 100",after);
                if(rows.isEmpty())return;
                for(var row:rows){long revision=number(row,"revision");cipher.open("model-config",revision,(String)row.get("sealed_snapshot"));cipher.open("mem0-llm",revision,(String)row.get("memory_envelope"));after=revision;}
            }
        }catch(Exception error){throw new IllegalStateException("模型配置与 Secret 无法核对 请恢复匹配的密钥和数据 拒绝覆盖已有配置");}
    }
    private Map<String,Object> lock(){return store.lockControl();}
    private long next(Map<String,Object> control){return store.nextRevision(control);}
    private long number(Map<String,Object> row,String name){return ((Number)row.get(name)).longValue();}
    private AgentActor supervisor(AgentActor actor){var fresh=users.current(actor.userId(),actor.username());if(!fresh.supervisor())throw new SecurityException("仅主管可维护模型配置");return new AgentActor(fresh.userId(),fresh.username(),AgentActor.Role.SUPERVISOR);}
    private AgentActor lockedSupervisor(AgentActor actor){
        if(!collaboration())return supervisor(actor);
        var fresh=users.lockCurrent(actor.userId(),actor.username());if(!fresh.supervisor())throw new SecurityException("仅主管可维护模型配置");
        return new AgentActor(fresh.userId(),fresh.username(),AgentActor.Role.SUPERVISOR);
    }
    private void request(String id){if(id==null||!id.matches("[A-Za-z0-9_-]{1,128}"))throw fail(400,"请求编号无效");}
    private String write(Object value){try{return json.writeValueAsString(value);}catch(Exception error){throw new IllegalStateException("模型配置编码失败");}}
    private String sha(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception error){throw new IllegalStateException("配置摘要失败");}}
    private String commandDigest(Object value){try{return sha(json.writer().with(com.fasterxml.jackson.databind.SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS).writeValueAsString(value));}catch(Exception invalid){throw new IllegalStateException("模型命令摘要编码失败");}}
    private AgentModelProperties copy(AgentModelProperties value){return json.convertValue(value,AgentModelProperties.class);}
    private AgentModelProperties.Connection connection(AgentModelProperties p,String provider){return switch(provider){case "dashscope"->p.getDashscope();case "deepseek"->p.getDeepseek();case "openai"->p.getOpenai();default->throw fail(400,"未知接入类型");};}
    private String provider(String id){if(id==null)throw fail(400,"模型编号缺失");if(id.startsWith("dashscope:"))return "dashscope";if(id.startsWith("deepseek:"))return "deepseek";if(id.startsWith("openai-official:"))return "openai";throw fail(400,"只支持现有三类模型接入");}
    private String name(String id){provider(id);String name=id.substring(id.indexOf(':')+1);if(!name.matches("[A-Za-z0-9][A-Za-z0-9._/\\-]{0,127}"))throw fail(400,"模型名称无效");return name;}
    private boolean revoked(String provider,String key){return key!=null&&!key.isBlank()&&store.revoked(provider,sha(key));}
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
    private void insert(long revision,long base,String status,Document doc,AgentModelProperties properties,Long creator,String request,String digest){String sealed=cipher.seal("model-config",revision,write(Map.of("properties",properties,"document",doc)));var memoryConnection=connection(properties,provider(doc.memoryModel()));String memoryEnvelope=cipher.seal("mem0-llm",revision,write(Map.of("provider",provider(doc.memoryModel()),"model",name(doc.memoryModel()),"api_key",memoryConnection.getApiKey(),"base_url",memoryConnection.getBaseUrl())));jdbc.update("INSERT INTO llm_configuration(revision,base_revision,status,document_json,sealed_snapshot,memory_envelope,creator_user_id,request_id,request_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,UTC_TIMESTAMP(6))",revision,base,status,write(doc),sealed,memoryEnvelope,creator,request,digest);}
    private Map<String,Object> row(long revision){var rows=jdbc.queryForList("SELECT * FROM llm_configuration WHERE revision=?",revision);if(rows.isEmpty())throw fail(404,"模型配置不存在");return rows.get(0);}
    public Runtime runtime(long revision){var row=row(revision);try{var node=json.readTree(cipher.open("model-config",revision,(String)row.get("sealed_snapshot")));return new Runtime(revision,json.treeToValue(node.get("document"),Document.class),json.treeToValue(node.get("properties"),AgentModelProperties.class));}catch(ResponseStatusException error){throw error;}catch(Exception error){throw new IllegalStateException("模型配置不能安全加载");}}
    public void assertUsable(long revision,String id){var r=runtime(revision);var status=row(revision).get("status");if(!Set.of("PUBLISHED","RETIRED").contains(status)||r.document().models().stream().noneMatch(option->option.enabled()&&option.id().equals(id))||!usable(r.properties(),provider(id)))throw fail(409,"任务引用的模型版本或凭证已不可用，请重新选择模型");}
    public Set<String> enabledIds(long revision){var r=runtime(revision);var providers=new HashSet<String>();for(String provider:List.of("dashscope","deepseek","openai"))if(usable(r.properties(),provider))providers.add(provider);return r.document().models().stream().filter(option->option.enabled()&&providers.contains(provider(option.id()))).map(Option::id).collect(java.util.stream.Collectors.toSet());}
    @Override public Active active(){long revision=store.activeRevision();var r=runtime(revision);return new Active(revision,r.document().defaultModel(),r.document().memoryModel());}
    @Override public void assertTaskConfiguration(long revision,String modelId){if(revision<1)throw fail(409,"原任务没有固定模型配置，请选择当前可用配置后再恢复");assertUsable(revision,modelId);}
    public View get(AgentActor actor,long revision){supervisor(actor);return view(revision);}
    private View view(long revision){var row=row(revision);var r=runtime(revision);var credentials=new LinkedHashMap<String,Boolean>();for(String provider:List.of("dashscope","deepseek","openai"))credentials.put(provider,usable(r.properties(),provider));var probes=store.probes(revision);return new View(revision,number(row,"base_revision"),(String)row.get("status"),r.document(),credentials,(String)row.get("memory_state"),probes,Long.toString(store.changeVersion()));}
    public List<View> list(AgentActor actor){supervisor(actor);var result=new ArrayList<>(jdbc.queryForList("SELECT revision FROM llm_configuration ORDER BY revision DESC LIMIT 30").stream().map(row->view(number(row,"revision"))).toList());long active=active().version();if(result.stream().noneMatch(view->view.revision()==active))result.add(view(active));return List.copyOf(result);}
    public View draft(AgentActor actor,Draft input){supervisor(actor);if(input==null||input.document()==null)throw fail(400,"模型配置缺失");request(input.requestId());return tx.execute(status->{var current=lockedSupervisor(actor);var control=lock();var keys=input.apiKeys()==null?Map.<String,String>of():input.apiKeys();for(var entry:keys.entrySet())if(!Set.of("dashscope","deepseek","openai").contains(entry.getKey())||entry.getValue()==null||entry.getValue().isBlank()||entry.getValue().length()>4096||entry.getValue().chars().anyMatch(Character::isISOControl))throw fail(400,"连接凭证格式无效");
        String digest=commandDigest(Map.of("base",input.baseRevision(),"document",input.document(),"keyDigests",keys.entrySet().stream().collect(java.util.stream.Collectors.toMap(Map.Entry::getKey,e->sha(e.getValue())))));
        String target=Long.toString(input.baseRevision());
        if(protectedCommands()){var replay=store.replay(current.userId(),input.requestId(),"DRAFT",target,digest,View.class);if(replay.found())return replay.response();}
        var previous=jdbc.queryForList("SELECT revision,request_sha256 FROM llm_configuration WHERE creator_user_id=? AND request_id=?",current.userId(),input.requestId());if(!previous.isEmpty()){if(!digest.equals(previous.get(0).get("request_sha256")))throw fail(409,"请求编号用于其他配置");if(protectedCommands())throw fail(409,"旧草稿命令缺少原始响应，请保留编号核对");return view(number(previous.get(0),"revision"));}
        if(number(control,"active_revision")!=input.baseRevision())throw fail(409,"生效版本已变化，请刷新");var base=runtime(input.baseRevision());var p=properties(input.document(),base.properties());keys.forEach((provider,key)->connection(p,provider).setApiKey(key));validate(input.document(),p);
        long beforeCounter=store.changeVersion(),revision=next(control);insert(revision,input.baseRevision(),"DRAFT",input.document(),p,current.userId(),input.requestId(),digest);
        var before=new LinkedHashMap<String,Object>();var after=historyFacts(revision);
        for(String provider:keys.keySet())if(!Objects.equals(connection(base.properties(),provider).getApiKey(),connection(p,provider).getApiKey())){before.put(provider+"Credential",false);after.put(provider+"Credential",true);}
        var changeReceipt=configHistory(current,revision,"DRAFT",input.requestId(),"SAVED",null,beforeCounter,before,after);
        var response=view(revision);if(protectedCommands())store.complete(current.userId(),input.requestId(),"DRAFT",target,digest,revision,response,changeReceipt);return response;
    });}
    private Long receipt(AgentActor actor,String request,String action,String target){
        return store.receipt(actor.userId(),request,action,target);
    }
    private void receipt(AgentActor actor,String request,String action,String target,long revision){
        store.receipt(actor.userId(),request,action,target,revision);
    }
    public View validate(AgentActor actor,long revision,String request){supervisor(actor);request(request);return tx.execute(status->{var current=lockedSupervisor(actor);var control=lock();String target=Long.toString(revision),digest=ModelConfigurationStore.digest("VALIDATE",target);
        if(protectedCommands()){var replay=store.replay(current.userId(),request,"VALIDATE",target,digest,View.class);if(replay.found())return replay.response();}
        else {var previous=receipt(current,request,"VALIDATE",target);if(previous!=null)return view(previous);}
        var row=row(revision);if(!Set.of("DRAFT","VALIDATED").contains(row.get("status")))throw fail(409,"配置不在草稿状态");if(number(control,"active_revision")!=number(row,"base_revision"))throw fail(409,"生效版本已变化，请重新创建草稿");var r=runtime(revision);validate(r.document(),r.properties());var old=runtime(number(row,"base_revision"));
        boolean changed=!old.document().memoryModel().equals(r.document().memoryModel())||!Objects.equals(connection(old.properties(),provider(old.document().memoryModel())).getApiKey(),connection(r.properties(),provider(r.document().memoryModel())).getApiKey());
        if(changed&&!store.hasPassedProbe(revision,r.document().memoryModel()))throw fail(409,"新的提炼连接须先通过一次 JSON 兼容检查");
        long counter=store.changeVersion();var before=historyFacts(revision);jdbc.update("UPDATE llm_configuration SET status='VALIDATED' WHERE revision=?",revision);
        var changeReceipt=configHistory(current,revision,"VALIDATE",request,"PASSED",counter,counter,before,historyFacts(revision));var response=view(revision);
        if(protectedCommands())store.complete(current.userId(),request,"VALIDATE",target,digest,revision,response,changeReceipt);else receipt(current,request,"VALIDATE",target,revision);return response;
    });}
    public record ProbeResult(long revision,String modelId,String requestId,String status){}
    public ProbeResult probeJson(AgentActor actor,long revision,String modelId,String requestId){
        var current=supervisor(actor);request(requestId);
        if(jsonProbe==null)throw fail(503,"JSON 检查未启用");
        boolean started=Boolean.TRUE.equals(tx.execute(status->{
            var fresh=lockedSupervisor(current);var control=lock();var stored=row(revision);
            var previous=store.probe(revision,requestId);
            if(previous.isPresent()){
                if(!Objects.equals(store.probeModel(previous.get()),modelId))throw fail(409,"检查请求编号已用于其他模型");
                return false;
            }
            if(!"DRAFT".equals(stored.get("status"))||number(control,"active_revision")!=number(stored,"base_revision"))throw fail(409,"请对当前版本的草稿执行检查");
            var snapshot=runtime(revision);validate(snapshot.document(),snapshot.properties());
            if(!Objects.equals(snapshot.document().memoryModel(),modelId))throw fail(400,"仅检查此草稿的提炼候选模型");
            if(!(stored.get("creator_user_id") instanceof Number owner)||owner.longValue()<=0)throw new IllegalStateException("模型草稿缺少可核对的所有者");
            if(!store.startProbe(revision,owner.longValue(),current.userId(),modelId,requestId))return false;
            long counter=store.changeVersion();var changeReceipt=configHistory(fresh,revision,"JSON_PROBE",requestId,"STARTED",counter,counter,
                    Map.of(),Map.of("probeStatus","STARTED","modelId",modelId));
            if(protectedCommands())store.probeOutcome(revision,requestId,new ProbeResult(revision,modelId,requestId,"STARTED"),changeReceipt);
            return true;
        }));
        if(started){
            boolean passed=jsonProbe.check(runtime(revision),modelId);
            tx.executeWithoutResult(status->{var fresh=lockedSupervisor(current);lock();
                // Reauthenticate before making this result available for validation.
                long counter=store.changeVersion();
                store.finishProbe(revision,requestId,passed);
                var changeReceipt=configHistory(fresh,revision,"JSON_PROBE",requestId,passed?"PASSED":"FAILED",counter,counter,
                        Map.of("probeStatus","STARTED","modelId",modelId),Map.of("probeStatus",passed?"PASSED":"FAILED","modelId",modelId));
                if(protectedCommands())store.probeOutcome(revision,requestId,new ProbeResult(revision,modelId,requestId,passed?"PASSED":"FAILED"),changeReceipt);
            });
        }
        return protectedCommands()?store.probeOutcome(revision,requestId):new ProbeResult(revision,modelId,requestId,store.probe(revision,requestId).orElseThrow().status());
    }
    public View publish(AgentActor actor,long revision,String request){var current=supervisor(actor);request(request);
        String target=Long.toString(revision),digest=ModelConfigurationStore.digest("PUBLISH",target);
        var completed=tx.execute(status->{lockedSupervisor(current);lock();
            if(protectedCommands())return store.replay(current.userId(),request,"PUBLISH",target,digest,View.class);
            var previous=receipt(current,request,"PUBLISH",target);return new ModelConfigurationStore.Replay<View>(previous!=null,previous==null?null:view(previous));});
        if(completed.found())return completed.response();
        var r=runtime(revision);validate(r.document(),r.properties());var bridge=memory.getIfAvailable();if(bridge==null)throw fail(503,"记忆配置桥接未启用，未发布新版本");
        var candidate=row(revision);if(!Set.of("VALIDATED","PUBLISHED").contains(candidate.get("status")))throw fail(409,"配置尚未校验，未提交记忆应用");bridge.prepare(revision,(String)candidate.get("memory_envelope"));
        var response=tx.execute(status->{var fresh=lockedSupervisor(current);var control=lock();
            if(protectedCommands()){var replay=store.replay(fresh.userId(),request,"PUBLISH",target,digest,View.class);if(replay.found())return replay.response();}
            else {var previous=receipt(fresh,request,"PUBLISH",target);if(previous!=null)return view(previous);}
            var stored=row(revision);
            var latestSnapshot=runtime(revision);validate(latestSnapshot.document(),latestSnapshot.properties());
            OperationsAuditApi.ChangeReceipt changeReceipt=null;
            if(!(number(control,"active_revision")==revision&&"PUBLISHED".equals(stored.get("status")))){
                if(!"VALIDATED".equals(stored.get("status"))||number(control,"active_revision")!=number(stored,"base_revision"))throw fail(409,"配置状态或当前版本已变化");
                long counter=store.changeVersion(),previousRevision=number(control,"active_revision");var before=historyFacts(revision);var previousFacts=historyFacts(previousRevision);
                jdbc.update("UPDATE llm_configuration SET status='RETIRED' WHERE revision=?",previousRevision);jdbc.update("UPDATE llm_configuration SET status='PUBLISHED',memory_state='PENDING',published_at=UTC_TIMESTAMP(6) WHERE revision=?",revision);store.activate(revision);
                changeReceipt=configHistory(fresh,revision,"PUBLISH",request,"APPLIED",counter,counter,before,historyFacts(revision));
                if(collaboration())configHistory(fresh,previousRevision,"RETIRE",request,"APPLIED",counter,counter,previousFacts,historyFacts(previousRevision));
            }
            var original=view(revision);if(protectedCommands())store.complete(fresh.userId(),request,"PUBLISH",target,digest,revision,original,changeReceipt);else receipt(fresh,request,"PUBLISH",target,revision);return original;
        });
        reconcileMemory();return protectedCommands()?response:view(revision);
    }
    /** Idempotent metadata reconciliation only; never generates memories or retries an LLM write. */
    @org.springframework.scheduling.annotation.Scheduled(fixedDelay=10000)
    public void reconcileMemory(){
        var bridge=memory.getIfAvailable();if(bridge==null)return;
        try{
            for(var key:store.pendingRevocations()){
                bridge.revokeCredential((String)key.get("key_sha256"));
                store.propagated((String)key.get("provider"),(String)key.get("key_sha256"));
            }
            var current=active();var stored=row(current.version());
            if(!"PENDING".equals(stored.get("memory_state")))return;
            var snapshot=runtime(current.version());
            if(!usable(snapshot.properties(),provider(snapshot.document().memoryModel())))return;
            if(bridge.appliedRevision()!=current.version())bridge.apply(current.version());
            if(bridge.appliedRevision()==current.version())jdbc.update("UPDATE llm_configuration SET memory_state='APPLIED' WHERE revision=? AND status='PUBLISHED'",current.version());
        }catch(RuntimeException ignored){/* Metadata stays pending. No extraction, credentials or exception bodies are logged. */}
    }
    @Override public void assertMemoryAvailable(){
        var current=active();var stored=row(current.version());var snapshot=runtime(current.version());
        if(!Set.of("ENVIRONMENT","APPLIED").contains(stored.get("memory_state"))||!usable(snapshot.properties(),provider(snapshot.document().memoryModel())))
            throw fail(503,"记忆提炼模型配置尚未应用或凭证已撤销，本次不会开始提炼");
    }
    public View restore(AgentActor actor,long revision,long base,String request){supervisor(actor);var old=runtime(revision);return draft(actor,new Draft(base,request,old.document(),Map.of()));}
    public void revoke(AgentActor actor,String provider,long revision,String request){supervisor(actor);request(request);tx.executeWithoutResult(status->{var current=lockedSupervisor(actor);var control=lock();String target=provider+":"+revision,digest=ModelConfigurationStore.digest("REVOKE_KEY",target);
        if(protectedCommands()){var replay=store.replay(current.userId(),request,"REVOKE_KEY",target,digest,Void.class);if(replay.found())return;}
        else if(receipt(current,request,"REVOKE_KEY",target)!=null)return;
        if(number(control,"active_revision")!=revision)throw fail(409,"生效版本已变化，请重新核对凭证");var key=connection(runtime(revision).properties(),provider).getApiKey();if(key==null||key.isBlank())throw fail(409,"此接入没有可撤销的凭证");
        boolean changed=!store.revoked(provider,sha(key));long counter=store.changeVersion();store.revoke(provider,sha(key),current.userId(),request);
        OperationsAuditApi.ChangeReceipt changeReceipt=null;
        if(!collaboration())audit.append(new OperationsAuditApi.Event(current,"ENTERPRISE","MODEL_CONFIG","REVOKE_KEY",provider,request,"APPLIED",revision));
        else if(changed)changeReceipt=configHistory(current,revision,"REVOKE_KEY",request,"APPLIED",counter,counter,Map.of(provider+"Credential",true),Map.of(provider+"Credential",false));
        if(protectedCommands())store.complete(current.userId(),request,"REVOKE_KEY",target,digest,revision,null,changeReceipt);else receipt(current,request,"REVOKE_KEY",target,revision);
    });reconcileMemory();}
    private LinkedHashMap<String,Object> historyFacts(long revision){
        var stored=row(revision);var document=runtime(revision).document();var fields=new LinkedHashMap<String,Object>();
        fields.put("status",stored.get("status"));fields.put("modelCatalog",bounded(document.models().stream().map(model->model.id()+"="+model.enabled()).toList()));
        fields.put("defaultModel",document.defaultModel());fields.put("fallbackModels",bounded(document.fallbackModels()));fields.put("fallbackEnabled",document.fallbackEnabled());
        fields.put("timeoutMs",document.timeoutMs());fields.put("firstTokenTimeoutMs",document.firstTokenTimeoutMs());fields.put("maxOutputTokens",document.maxOutputTokens());
        fields.put("memoryModel",document.memoryModel());fields.put("activeRevision",Long.toString(store.activeRevision()));return fields;
    }
    private String bounded(Object value){String text=write(value);return text.length()<=512?text:text.substring(0,430)+"… sha256:"+sha(text);}
    private OperationsAuditApi.ChangeReceipt configHistory(AgentActor actor,long revision,String action,String request,String result,Long beforeVersion,long counter,
                               Map<String,Object> before,Map<String,Object> after){
        if(!collaboration()){audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","MODEL_CONFIG",action,Long.toString(revision),request,result,revision));return null;}
        if(before.equals(after))return null;long version=store.changeVersion();if(version<=counter)version=store.advanceChangeVersion();
        return collaborationHistory.record(actor,"MODEL_CONFIG","LLM_CONFIGURATION",Long.toString(revision),action,request,result,beforeVersion,version,before,after,
                Set.of("dashscopeCredential","deepseekCredential","openaiCredential"));
    }
    public static ResponseStatusException fail(int code,String message){return new ResponseStatusException(HttpStatus.valueOf(code),message);}
}
