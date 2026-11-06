package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.Source;
import com.ruanzhu.doorhandle.module.ai.research.ResearchSourceRepository;
import com.ruanzhu.doorhandle.framework.persistence.chat.JdbcMessageEvidenceStore;
import io.agentscope.core.message.*;
import io.agentscope.core.state.AgentState;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import com.ruanzhu.doorhandle.module.ai.context.DurableContextPersistence.*;
import com.ruanzhu.doorhandle.module.ai.context.DurableContextProtocols.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import jakarta.annotation.PostConstruct;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Account-private summaries, provenance and offload receipts; no SDK state is returned to a browser. */
@Service
@ConditionalOnProperty(prefix="agentscope.context-store",name="enabled",havingValue="true")
public class DurableContextStore implements ContextFileAccessApi {
    public static final String READ="read_context_file",POLICY="durable-context-v1";
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final ObjectMapper json;private final JdbcMessageEvidenceStore messageEvidence;
    private final ObjectProvider<AgentContextDataApi> data;private final ContextProvenance provenance;
    private final DurableContextPersistence persistence;private ObjectProvider<ChildProvenanceReader> childReaders;
    @Autowired public void childReaders(ObjectProvider<ChildProvenanceReader> readers){this.childReaders=readers;}
    @Value("${agentscope.context-store.offload-enabled:false}") private boolean offloadEnabled;
    @Value("${agentscope.workbench.enabled:false}") private boolean workbenchEnabled;
    @Value("${agentscope.workbench.recovery:true}") private boolean recoveryEnabled;
    @Value("${agentscope.workbench.files:true}") private boolean filesEnabled;
    @Value("${agentscope.workbench.children:true}") private boolean childrenEnabled=true;
    @Value("${agentscope.ai.context-compaction.enabled:false}") private boolean compactionEnabled;
    public DurableContextStore(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,ObjectProvider<AgentContextDataApi> data){this.jdbc=jdbc;tx=new TransactionTemplate(manager);this.json=json;this.data=data;provenance=new ContextProvenance(json);messageEvidence=new JdbcMessageEvidenceStore(jdbc,json);persistence=new DurableContextPersistence(jdbc,json);}
    @PostConstruct public void validate(){if(!workbenchEnabled||!recoveryEnabled||!compactionEnabled||!childrenEnabled)throw new IllegalStateException("持久上下文需要工作台、检查点恢复、持久专业任务和上下文压缩");if(offloadEnabled&&!filesEnabled)throw new IllegalStateException("工具结果卸载需要启用会话文件工作区");persistence.validateSchema();jdbc.queryForList("SELECT id,context_owner_user_id,context_sources_json,context_sources_sha256 FROM chat_message WHERE 1=0");}
    public boolean offloadEnabled(){return offloadEnabled;}
    @Override public void assertReadable(AgentActor actor,String session,String fileId){
        var rows=persistence.offloads(actor.userId(),session,null,null,fileId,1001,false);
        if(rows.isEmpty())throw new SecurityException("上下文资料回执不存在");
        if(rows.size()>1000)throw new IllegalStateException("上下文资料来源超过读取上限");
        for(var row:rows)authorize(actor,session,checkedSources(row.body()),new HashSet<>());
    }
    public record Bootstrap(long through,List<Msg> initial,boolean ready){}
    public Bootstrap bootstrap(AgentActor actor,String session,String scope,String task,List<Msg> initial){
        data().authorize(actor,session,List.of());
        var saved=persistence.bootstrap(actor.userId(),session,task,false);
        if(saved.isEmpty()){
            if(initial==null||initial.isEmpty())throw new IllegalStateException("持久上下文启动资料未绑定");
            long through=scope.equals("main")?data().history(actor,session,0,0,1).throughId():0;
            String initialState=state(actor,initial),digest=bootstrapHash(actor,session,scope,task,through,initialState);
            var reservation=tx.execute(status->{var r=persistence.reserve(actor.userId(),session,task,through,new ContextBootstrapV1(scope,initialState,digest,null));
                if(r.created())audit(actor,session,scope,task,"CONTEXT_RESERVED",digest);return r;});
            saved=Optional.of(reservation.boot());
        }
        var row=saved.orElseThrow();if(!scope.equals(row.body().agentScope()))throw new SecurityException("上下文执行范围不一致");
        return new Bootstrap(row.through(),AgentState.fromJsonString(row.body().initialState()).getContext(),row.ready());
    }
    public void initialized(AgentActor actor,String session,String scope,String task,Runnable checkpoint){
        tx.executeWithoutResult(status->{persistence.requireSession(actor.userId(),session);
            var row=persistence.bootstrap(actor.userId(),session,task,true).orElseThrow(()->new IllegalStateException("持久上下文启动资料未绑定"));
            if(!scope.equals(row.body().agentScope()))throw new SecurityException("上下文执行范围不一致");
            checkpoint.run();if(!row.ready()){persistence.initialized(row);audit(actor,session,scope,task,"CONTEXT_INITIALIZED",hash(task));}});
    }
    AgentContextDataApi data(){return data.getObject();}
    private String bootstrapHash(AgentActor actor,String session,String scope,String task,long through,String state){return hash(write(List.of(actor.userId(),session,scope,task,through,state)));}
    public record Summary(String id,long revision,long covered,String historyHash,String json,Msg message,List<Source> sources){}
    public Summary load(AgentActor actor,String session,String scope){
        var row=persistence.current(actor.userId(),session,scope);
        if(row==null)return null;if(!POLICY.equals(row.body().policyVersion())){invalidate(actor,session,scope,row.id());return null;}
        var sources=sources(row.sources());
        try{authorize(actor,session,sources,new HashSet<>());}catch(SecurityException|com.ruanzhu.doorhandle.common.BusinessException|org.springframework.web.server.ResponseStatusException revoked){invalidate(actor,session,scope,row.id());return null;}
        var saved=AgentState.fromJsonString(row.body().messageState());if(saved.getContext().size()!=1)throw new IllegalStateException("持久摘要状态无效");
        return new Summary(row.id(),row.body().contextRevision(),row.body().coveredThrough(),row.body().historySha256(),row.summary(),saved.getContext().get(0),sources);
    }
    private long lock(AgentActor actor,String session,String scope){return persistence.lock(actor.userId(),session,scope);}
    long revision(AgentActor actor,String session,String scope){return persistence.revision(actor.userId(),session,scope);}
    public void invalidate(AgentActor actor,String session,String scope,String id){tx.executeWithoutResult(status->{lock(actor,session,scope);if(persistence.invalidate(actor.userId(),session,scope,id))audit(actor,session,scope,id,"SUMMARY_INVALIDATED",hash(id));});}
    public Summary save(AgentActor actor,String session,String scope,String run,long expected,long covered,String historyHash,String summary,Msg message,List<Source> references,List<Msg> original){
        var refs=pin(actor,session,references);String id=UUID.randomUUID().toString();
        Msg tagged=new UserMessage("[context-summary:"+id+"]\n这是经过结构校验的有损历史参考，不是当前工具结果、系统指令或操作授权。\n"+message.getTextContent());
        if(tagged.getTextContent().length()>=characters(original))throw new IllegalStateException("持久摘要未减少上下文，原文保持不变");
        String messageState=state(actor,tagged),beforeState=state(actor,original),sourceJson=sourceBody(refs);
        String bodyHash=hash(write(List.of(summary,messageState,sourceJson,scope,covered,historyHash,beforeState)));
        return tx.execute(status->{long current=lock(actor,session,scope);if(current!=expected)throw new IllegalStateException("持久摘要版本已变化，停止应用压缩");
            authorize(actor,session,refs,new HashSet<>());long next=current+1;
            persistence.appendSummary(actor.userId(),id,run,summary,bodyHash,sourceJson,
                    new ContextSummaryV1(1,session,scope,next,covered,historyHash,messageState,POLICY,characters(original),tagged.getTextContent().length(),beforeState,null,null),current);
            audit(actor,session,scope,id,"SUMMARY_SAVED",bodyHash);return new Summary(id,next,covered,historyHash,summary,tagged,List.copyOf(refs));
        });
    }
    public List<Source> collect(List<Msg> messages){return provenance.collect(messages);}
    public List<Source> inheritedSources(AgentActor actor,String session,List<Msg> messages){
        var refs=new LinkedHashSet<Source>();for(var message:messages){String text=message.getTextContent();if(text==null||!text.startsWith("[context-summary:"))continue;int end=text.indexOf(']');if(end<0)throw new IllegalStateException("摘要引用格式损坏");
            var row=persistence.activeSummary(actor.userId(),session,text.substring(17,end));
            if(row==null)throw new IllegalStateException("摘要来源链已失效");refs.addAll(sources(row.sources()));
        }return List.copyOf(refs);
    }
    private List<Source> pin(AgentActor actor,String session,List<Source> sources){
        var all=new LinkedHashSet<>(snapshotChildren(actor,session,sources,new HashSet<>(),new HashSet<>()));all.add(new Source("ROLE",actor.role().name(),""));authorize(actor,session,List.copyOf(all),new HashSet<>());
        var plain=all.stream().filter(s->!s.kind().equals("RESEARCH")).toList();var result=new ArrayList<>(data().pin(actor,session,plain));for(var source:all)if(source.kind().equals("RESEARCH")){var hashes=new ResearchSourceRepository(jdbc).activeHashes(actor.userId(),source.resourceId());if(hashes.size()!=1)throw new SecurityException("引用来源已失效");result.add(new Source("RESEARCH",source.resourceId(),hashes.get(0)));}return List.copyOf(result);
    }
    /** Snapshot the sources consumed by a child now, rather than following its future conversations. */
    private List<Source> snapshotChildren(AgentActor actor,String session,List<Source> sources,Set<String> active,Set<String> expanded){
        var result=new LinkedHashSet<Source>();
        for(var source:sources){
            if(!source.kind().equals("CHILD"))result.add(source);
            else{
                if(active.contains(source.resourceId()))throw new SecurityException("专业来源出现循环");
                if(!expanded.add(source.resourceId()))continue;
                if(expanded.size()>32||active.size()>=16)throw new SecurityException("专业来源关联超出上限");
                var child=child(actor,session,source.resourceId());
                var nested=originSources(actor,session,"child:"+source.resourceId(),null);
                if(nested.isEmpty()&&"COMPLETED".equals(child.status()))throw new IllegalStateException("已完成专业任务缺少来源回执");
                active.add(source.resourceId());result.addAll(snapshotChildren(actor,session,nested,active,expanded));active.remove(source.resourceId());
            }
            if(result.size()>2000)throw new IllegalStateException("专业来源快照超过本轮上限");
        }
        return List.copyOf(result);
    }
    private List<Source> forkSources(AgentActor actor,String source,String target,List<Source> refs){
        try{var snapshot=pin(actor,source,refs);return authorized(actor,target,snapshot)?pin(actor,target,snapshot):null;}
        catch(SecurityException|com.ruanzhu.doorhandle.common.BusinessException|org.springframework.web.server.ResponseStatusException revoked){return null;}
    }
    private void authorize(AgentActor actor,String session,List<Source> sources,Set<String> visited){
        data().authorize(actor,session,sources.stream().filter(s->!Set.of("RESEARCH","CHILD").contains(s.kind())).toList());
        for(var source:sources)if(source.kind().equals("FILE")&&visited.add("file:"+source.resourceId())){
            if(visited.size()>64)throw new SecurityException("上下文文件来源关联超出上限");
            var receipts=persistence.offloads(actor.userId(),session,null,null,source.resourceId(),1001,false);
            if(receipts.size()>1000)throw new SecurityException("上下文文件来源超过读取上限");
            for(var row:receipts)authorize(actor,session,checkedSources(row.body()),visited);
        }
        for(var source:sources)if(source.kind().equals("RESEARCH")){
            var found=new ResearchSourceRepository(jdbc).activeHashes(actor.userId(),source.resourceId());
            if(found.size()!=1||!source.version().isEmpty()&&!source.version().equals(found.get(0)))throw new SecurityException("引用来源已失效");
        }else if(source.kind().equals("CHILD")&&visited.add(source.resourceId())){
            if(visited.size()>32)throw new SecurityException("专业来源关联超出上限");
            var child=child(actor,session,source.resourceId());
            authorize(actor,session,originSources(actor,child.sessionId(),"child:"+source.resourceId(),null),visited);
        }
    }
    private ChildProvenanceReader.ChildProvenance child(AgentActor actor,String session,String id){
        var reader=childReaders==null?null:childReaders.getIfAvailable();
        if(reader==null)throw new IllegalStateException("专业来源读取器尚未装配");
        var child=reader.find(actor.userId(),session,id).orElseThrow(()->new SecurityException("专业来源不属于当前会话"));
        if(child.ownerUserId()!=actor.userId()||!session.equals(child.sessionId())||!id.equals(child.id()))throw new SecurityException("专业来源身份不一致");
        return child;
    }
    public void validateMessages(AgentActor actor,String session,Set<String> scopes,List<Msg> messages){
        for(var message:messages){String text=message.getTextContent();if(text==null||!text.startsWith("[context-summary:"))continue;
            int end=text.indexOf(']');if(end<0)throw new IllegalStateException("检查点摘要标记损坏");String id=text.substring(17,end);
            var row=persistence.activeSummary(actor.userId(),session,id);
            if(row==null||!scopes.contains(row.body().agentScope())||!POLICY.equals(row.body().policyVersion()))throw new IllegalStateException("检查点摘要已失效或损坏，请核对后开始新任务");
            var saved=AgentState.fromJsonString(row.body().messageState());if(saved.getContext().size()!=1||!text.equals(saved.getContext().get(0).getTextContent()))throw new IllegalStateException("检查点摘要正文与回执不一致");
            authorize(actor,session,sources(row.sources()),new HashSet<>());
        }
    }
    public List<Source> taskSources(AgentActor actor,String session,String task){return originSources(actor,session,null,task);}
    /** Raw checkpoint results need the same current permission checks as tagged summaries. */
    public void assertTaskReadable(AgentActor actor,String session,String task){authorize(actor,session,taskSources(actor,session,task),new HashSet<>());}
    public boolean authorized(AgentActor actor,String session,List<Source> sources){try{authorize(actor,session,sources,new HashSet<>());return true;}catch(SecurityException|com.ruanzhu.doorhandle.common.BusinessException|org.springframework.web.server.ResponseStatusException denied){return false;}}
    public void fork(AgentActor actor,String source,String target,long through){
        var mapping=data().forkMessages(actor,source,target,through);var ids=new HashMap<Long,Long>();mapping.forEach(pair->ids.put(pair.sourceId(),pair.targetId()));
        tx.executeWithoutResult(status->{
            lock(actor,target,"turn-links");
            for(var pair:mapping){var refs=turnSources(actor,source,pair.sourceId());if(refs==null)continue;var checked=forkSources(actor,source,target,refs);if(checked==null)continue;String body=sourceBody(checked);
                storeTurnSources(actor,target,pair.targetId(),body);
            }
            var offloads=persistence.offloads(actor.userId(),source,null,null,null,1001,false);
            if(offloads.size()>1000)throw new IllegalStateException("分支上下文资料超过本次上限，未省略后继续");
            for(var offload:offloads){
                String file=offload.file();if(!authorized(actor,target,List.of(new Source("FILE",file,offload.body().contentSha256()))))continue;
                var refs=forkSources(actor,source,target,checkedSources(offload.body()));if(refs==null)continue;
                String id=UUID.randomUUID().toString(),body=sourceBody(refs),originalScope=offload.scope();
                String inheritedScope="main".equals(originalScope)?"main":"inherited:"+hash(source+":"+originalScope);
                persistence.appendOffload(actor.userId(),target,inheritedScope,hash("fork:"+offload.id()),id,file,
                        new OffloadEvidenceV1(offload.body().contentSha256(),offload.body().byteLength(),body,hash(body),null,null,"FORK",offload.id(),source,through));
            }
            var row=persistence.forkCandidate(actor.userId(),source,through);
            if(row!=null){
                long covered=row.body().coveredThrough();var refs=forkSources(actor,source,target,sources(row.sources()));
                if(refs!=null&&ids.containsKey(covered)&&data().historyDigest(actor,source,covered).equals(row.body().historySha256())){
                    long next=ids.get(covered);
                    if(revision(actor,target,"main")==0)save(actor,target,"main","fork-"+row.id(),0,next,data().historyDigest(actor,target,next),row.summary(),new UserMessage(row.summary()),refs,AgentState.fromJsonString(row.body().originalState()).getContext());
                }
            }
            audit(actor,target,"main",UUID.nameUUIDFromBytes((source+":"+through).getBytes(StandardCharsets.UTF_8)).toString(),"CONTEXT_FORKED",hash(source+":"+through));
        });
    }
    public void recordResult(AgentActor actor,String session,String scope,String task,String run,String callKey,String tool,Map<String,Object> input,ToolResultBlock result){
        // The workbench binds tool/input/result to this call key. Reusing its completed result
        // must also reuse the original child-source snapshot, not the child's later conversations.
        var existing=persistence.origin(actor.userId(),session,scope,callKey);
        if(existing!=null){
            if(!task.equals(existing.task()))throw new IllegalStateException("工具来源执行归属冲突");
            authorize(actor,session,checkedSources(existing.body()),new HashSet<>());return;
        }
        var refs=provenance.tool(tool,input==null?Map.of():input,result);
        recordOrigin(actor,session,scope,task,run,callKey,pin(actor,session,refs));
    }
    public void recordSeed(AgentActor actor,String session,String scope,String task,String run,List<Source> sources){recordOrigin(actor,session,scope,task,run,hash("seed:"+task),pin(actor,session,sources));}
    private void recordOrigin(AgentActor actor,String session,String scope,String task,String run,String callKey,List<Source> refs){
        String body=sourceBody(refs),digest=hash(body);
        tx.executeWithoutResult(status->{if(persistence.appendOrigin(actor.userId(),session,scope,task,run,callKey,new OriginEvidenceV1(body,digest)))
            audit(actor,session,scope,UUID.nameUUIDFromBytes(callKey.getBytes(StandardCharsets.UTF_8)).toString(),"ORIGIN_SAVED",digest);});
    }
    private List<Source> originSources(AgentActor actor,String session,String scope,String task){
        var rows=persistence.origins(actor.userId(),session,scope,task);
        if(rows.size()>512)throw new IllegalStateException("工具来源历史超过本次读取上限，未省略后继续");
        var refs=new LinkedHashSet<Source>();for(var row:rows){refs.addAll(checkedSources(row.body()));if(refs.size()>2000)throw new IllegalStateException("工具来源集合超过本次上限");}return List.copyOf(refs);
    }
    public void turnSaved(AgentActor actor,String session,String task,long message){var refs=pin(actor,session,originSources(actor,session,null,task));String body=sourceBody(refs);tx.executeWithoutResult(status->{lock(actor,session,"turn-links");if(storeTurnSources(actor,session,message,body))audit(actor,session,"main",UUID.nameUUIDFromBytes((session+":"+message).getBytes(StandardCharsets.UTF_8)).toString(),"TURN_LINKED",hash(body));});}
    private boolean storeTurnSources(AgentActor actor,String session,long message,String body){
        return messageEvidence.saveSources(actor.userId(),session,message,body);
    }
    public List<Source> turnSources(AgentActor actor,String session,long message){String body=messageEvidence.loadSources(actor.userId(),session,message);return body==null?null:sources(body);}
    public ToolResultBlock offload(AgentActor actor,String session,String scope,String key,ToolResultBlock result){
        if(!offloadEnabled||result.getState()!=null&&Set.of("ERROR","FAILED").contains(result.getState().name())||result.getOutput().stream().anyMatch(block->!(block instanceof TextBlock)))return result;
        String text=ContextProvenance.text(result);byte[] bytes=text.getBytes(StandardCharsets.UTF_8);if(bytes.length<=16384)return result;
        if(bytes.length>2097152)throw new IllegalStateException("工具结果超过受控卸载上限，未截断后继续");
        var origin=persistence.origin(actor.userId(),session,scope,key);
        if(origin==null)throw new IllegalStateException("工具来源回执缺失，未生成缺少授权依据的卸载资料");
        var refs=pin(actor,session,checkedSources(origin.body()));String digest=hash(text);
        return tx.execute(status->{
            var rows=persistence.offloads(actor.userId(),session,scope,key,null,2,false);
            if(rows.size()>1)throw new IllegalStateException("卸载结果身份不唯一");
            String fileId;if(!rows.isEmpty()){
                var previous=rows.get(0);if(!DurableContextProtocols.digest(digest,previous.body().contentSha256())||previous.body().byteLength()!=bytes.length)throw new IllegalStateException("卸载结果摘要冲突");
                authorize(actor,session,checkedSources(previous.body()),new HashSet<>());fileId=previous.file();
            }else{
                var file=data().saveContextFile(actor,session,hash(scope+":"+key+":"+digest),text);fileId=file.id();String id=UUID.randomUUID().toString();
                String body=sourceBody(refs);var saved=persistence.appendOffload(actor.userId(),session,scope,key,id,fileId,new OffloadEvidenceV1(digest,bytes.length,body,hash(body),null,null,"TOOL",null,null,null));
                if(saved.id().equals(id))audit(actor,session,scope,id,"TOOL_RESULT_OFFLOADED",digest);
            }
            data().authorize(actor,session,List.of(new Source("FILE",fileId,digest)));
            String excerpt=text.codePoints().limit(1200).collect(StringBuilder::new,StringBuilder::appendCodePoint,StringBuilder::append).toString();
            return ToolResultBlock.text("[已完成工具结果的有界摘录，不代表完整内容]\n"+excerpt+"\n[完整结果已保存为当前 Agent 的私有上下文资料]\nfileId="+fileId+"\nsha256="+digest+"\nbytes="+bytes.length+"\n需要后续内容时使用 read_context_file，必须提供 fileId、sha256 和 offset；不能从摘录推断完整结论。");
        });
    }
    public AgentContextDataApi.Slice read(AgentActor actor,String session,String scope,String id,String sha,int offset,int limit){
        var rows=persistence.offloads(actor.userId(),session,scope,null,id,2,false);
        if(rows.size()!=1||!DurableContextProtocols.digest(sha,rows.get(0).body().contentSha256()))throw new SecurityException("此上下文文件不属于当前 Agent 或摘要不匹配");
        authorize(actor,session,checkedSources(rows.get(0).body()),new HashSet<>());return data().readContextFile(actor,session,id,sha,offset,limit);
    }
    public List<AgentWorkbenchApi.Item> views(AgentActor actor,String session){data().authorize(actor,session,List.of());var result=new ArrayList<AgentWorkbenchApi.Item>();
        for(var row:persistence.heads(actor.userId(),session)){
            var body=row.body();var fields=new LinkedHashMap<String,Object>();fields.put("title","持久上下文摘要");fields.put("phase","PERSISTED");fields.put("agentScope",body.agentScope());fields.put("coveredThrough",body.coveredThrough());fields.put("beforeChars",body.beforeChars());fields.put("afterChars",body.afterChars());fields.put("basis","CHARACTER_ESTIMATE");fields.put("text","摘要仅作为历史参考，权限变化时重新核对；原始聊天和工具回执保留");
            result.add(new AgentWorkbenchApi.Item(row.id(),"CONTEXT",row.status(),body.contextRevision(),fields,row.created().toString()));
        }
        for(var row:persistence.offloads(actor.userId(),session,null,null,null,30,true))result.add(new AgentWorkbenchApi.Item(row.id(),"CONTEXT","COMPLETED",0,Map.of("title","工具上下文资料","phase","OFFLOADED","agentScope",row.scope(),"fileId",row.file(),"byteLength",row.body().byteLength(),"sha256",row.body().contentSha256(),"text","模型仅接收摘录，可通过受控工具分段读取完整结果"),row.created().toString()));return List.copyOf(result);
    }
    private List<Source> sources(String body){try{
        if(body==null||body.length()>1048576)throw new IllegalArgumentException();
        List<Source> refs=json.readValue(body,new TypeReference<List<Source>>(){});
        if(refs==null||refs.size()>2000||refs.stream().anyMatch(source->source==null||source.kind()==null||!Set.of("ROLE","FILE","TASK","REPORT","DEVICE","ALERT","MODEL","RESEARCH","CHILD","BUSINESS_FILE","BUSINESS_IMAGE").contains(source.kind())||source.resourceId()==null||source.resourceId().isBlank()||source.resourceId().length()>256||source.version()==null||source.version().length()>256))throw new IllegalArgumentException();
        return List.copyOf(refs);
    }catch(Exception invalid){throw new IllegalStateException("上下文来源格式或资源边界无效");}}
    private String sourceBody(List<Source> refs){String body=write(refs);sources(body);return body;}
    private List<Source> checkedSources(OriginEvidenceV1 body){return checkedSources(body.sourcesJson(),body.sourcesSha256());}
    private List<Source> checkedSources(OffloadEvidenceV1 body){return checkedSources(body.sourcesJson(),body.sourcesSha256());}
    private List<Source> checkedSources(String body,String digest){if(!DurableContextProtocols.digest(hash(body),digest))throw new IllegalStateException("上下文来源回执损坏");return sources(body);}
    private String state(AgentActor actor,Msg message){return state(actor,List.of(message));}
    private String state(AgentActor actor,List<Msg> messages){return AgentState.builder().userId(Long.toString(actor.userId())).sessionId("private-context").context(messages).build().toJson();}
    static long characters(List<Msg> messages){return messages.stream().flatMap(m->m.getContent().stream()).mapToLong(b->ContextProvenance.text(b).length()).sum();}
    String write(Object value){try{return json.writeValueAsString(value);}catch(Exception invalid){throw new IllegalStateException("上下文无法序列化");}}
    static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception invalid){throw new IllegalStateException(invalid);}}
    private void audit(AgentActor actor,String session,String scope,String id,String action,String digest){persistence.audit(actor.userId(),session,scope,id,action,digest);}
}
