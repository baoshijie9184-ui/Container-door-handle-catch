package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.agent.AgentContextDataApi.Source;
import io.agentscope.core.message.*;
import io.agentscope.core.state.AgentState;
import org.springframework.beans.factory.ObjectProvider;
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
    private final JdbcTemplate jdbc;private final TransactionTemplate tx;private final ObjectMapper json;
    private final ObjectProvider<AgentContextDataApi> data;private final ContextProvenance provenance;
    @Value("${agentscope.context-store.offload-enabled:false}") private boolean offloadEnabled;
    @Value("${agentscope.workbench.enabled:false}") private boolean workbenchEnabled;
    @Value("${agentscope.workbench.recovery:true}") private boolean recoveryEnabled;
    @Value("${agentscope.workbench.files:true}") private boolean filesEnabled;
    @Value("${agentscope.workbench.children:true}") private boolean childrenEnabled=true;
    @Value("${agentscope.ai.context-compaction.enabled:false}") private boolean compactionEnabled;
    public DurableContextStore(JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,ObjectProvider<AgentContextDataApi> data){this.jdbc=jdbc;tx=new TransactionTemplate(manager);this.json=json;this.data=data;provenance=new ContextProvenance(json);}
    @PostConstruct public void validate(){if(!workbenchEnabled||!recoveryEnabled||!compactionEnabled||!childrenEnabled)throw new IllegalStateException("持久上下文需要工作台、检查点恢复、持久专业任务和上下文压缩");if(offloadEnabled&&!filesEnabled)throw new IllegalStateException("工具结果卸载需要启用会话文件工作区");for(String table:List.of("agent_context_head","agent_context_summary","agent_context_offload","agent_context_origin","agent_context_turn","agent_context_audit","agent_context_bootstrap"))jdbc.queryForList("SELECT * FROM "+table+" WHERE 1=0");}
    public boolean offloadEnabled(){return offloadEnabled;}
    @Override public void assertReadable(AgentActor actor,String session,String fileId){
        var rows=jdbc.queryForList("SELECT sources_json,sources_sha256 FROM agent_context_offload WHERE user_id=? AND session_id=? AND file_id=?",actor.userId(),session,fileId);
        if(rows.isEmpty())throw new SecurityException("上下文资料回执不存在");for(var row:rows)authorize(actor,session,checkedSources(row),new HashSet<>());
    }
    public record Bootstrap(long through,List<Msg> initial,boolean ready){}
    public Bootstrap bootstrap(AgentActor actor,String session,String scope,String task,List<Msg> initial){
        var rows=jdbc.queryForList("SELECT * FROM agent_context_bootstrap WHERE user_id=? AND session_id=? AND logical_task_id=?",actor.userId(),session,task);
        if(rows.isEmpty()){
            if(initial==null||initial.isEmpty())throw new IllegalStateException("持久上下文启动资料未绑定");
            long through=scope.equals("main")?data().history(actor,session,0,0,1).throughId():0;
            String initialState=state(actor,initial),digest=bootstrapHash(actor,session,scope,task,through,initialState);tx.executeWithoutResult(status->{jdbc.update("INSERT INTO agent_context_bootstrap(user_id,session_id,logical_task_id,agent_scope,history_through,initial_state,initial_sha256) VALUES(?,?,?,?,?,?,?)",actor.userId(),session,task,scope,through,initialState,digest);audit(actor,session,scope,task,"CONTEXT_RESERVED",digest);});
            return new Bootstrap(through,List.copyOf(initial),false);
        }
        var row=rows.get(0);if(!scope.equals(row.get("agent_scope")))throw new SecurityException("上下文执行范围不一致");
        if(!bootstrapHash(actor,session,scope,task,((Number)row.get("history_through")).longValue(),(String)row.get("initial_state")).equals(row.get("initial_sha256")))throw new IllegalStateException("上下文启动资料损坏");
        return new Bootstrap(((Number)row.get("history_through")).longValue(),AgentState.fromJsonString((String)row.get("initial_state")).getContext(),((Number)row.get("initialized")).intValue()==1);
    }
    public void initialized(AgentActor actor,String session,String scope,String task,Runnable checkpoint){
        tx.executeWithoutResult(status->{jdbc.queryForMap("SELECT initialized FROM agent_context_bootstrap WHERE user_id=? AND session_id=? AND logical_task_id=? FOR UPDATE",actor.userId(),session,task);checkpoint.run();jdbc.update("UPDATE agent_context_bootstrap SET initialized=1 WHERE user_id=? AND session_id=? AND logical_task_id=?",actor.userId(),session,task);audit(actor,session,scope,task,"CONTEXT_INITIALIZED",hash(task));});
    }
    AgentContextDataApi data(){return data.getObject();}
    private String bootstrapHash(AgentActor actor,String session,String scope,String task,long through,String state){return hash(write(List.of(actor.userId(),session,scope,task,through,state)));}
    public record Summary(String id,long revision,long covered,String historyHash,String json,Msg message,List<Source> sources){}
    public Summary load(AgentActor actor,String session,String scope){
        var rows=jdbc.queryForList("SELECT s.* FROM agent_context_head h JOIN agent_context_summary s ON s.summary_id=h.summary_id WHERE h.user_id=? AND h.session_id=? AND h.agent_scope=? AND s.status='ACTIVE'",actor.userId(),session,scope);
        if(rows.isEmpty())return null;var row=rows.get(0);String body=(String)row.get("summary_json");if(!summaryHash(row).equals(row.get("summary_sha256")))throw new IllegalStateException("持久摘要损坏，未加载");if(!POLICY.equals(row.get("policy_version"))){invalidate(actor,session,scope,(String)row.get("summary_id"));return null;}
        var sources=sources((String)row.get("sources_json"));
        try{authorize(actor,session,sources,new HashSet<>());}catch(SecurityException|com.ruanzhu.doorhandle.common.BusinessException|org.springframework.web.server.ResponseStatusException revoked){invalidate(actor,session,scope,(String)row.get("summary_id"));return null;}
        String messageState=(String)row.get("message_state");var state=AgentState.fromJsonString(messageState);if(state.getContext().size()!=1)throw new IllegalStateException("持久摘要状态无效");
        return new Summary((String)row.get("summary_id"),((Number)row.get("revision")).longValue(),((Number)row.get("covered_through")).longValue(),(String)row.get("history_sha256"),body,state.getContext().get(0),sources);
    }
    private long lock(AgentActor actor,String session,String scope){jdbc.update("INSERT INTO agent_context_head(user_id,session_id,agent_scope) VALUES(?,?,?) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id)",actor.userId(),session,scope);return jdbc.queryForObject("SELECT revision FROM agent_context_head WHERE user_id=? AND session_id=? AND agent_scope=? FOR UPDATE",Long.class,actor.userId(),session,scope);}
    long revision(AgentActor actor,String session,String scope){var rows=jdbc.queryForList("SELECT revision FROM agent_context_head WHERE user_id=? AND session_id=? AND agent_scope=?",actor.userId(),session,scope);return rows.isEmpty()?0:((Number)rows.get(0).get("revision")).longValue();}
    public void invalidate(AgentActor actor,String session,String scope,String id){tx.executeWithoutResult(status->{lock(actor,session,scope);int changed=jdbc.update("UPDATE agent_context_summary SET status='INVALIDATED' WHERE summary_id=? AND user_id=? AND session_id=? AND status='ACTIVE'",id,actor.userId(),session);if(changed==1){jdbc.update("UPDATE agent_context_head SET revision=revision+1 WHERE user_id=? AND session_id=? AND agent_scope=? AND summary_id=?",actor.userId(),session,scope,id);audit(actor,session,scope,id,"SUMMARY_INVALIDATED",hash(id));}});}
    public Summary save(AgentActor actor,String session,String scope,String run,long expected,long covered,String historyHash,String summary,Msg message,List<Source> references,List<Msg> original){
        var refs=pin(actor,session,references);String id=UUID.randomUUID().toString();
        Msg tagged=new UserMessage("[context-summary:"+id+"]\n这是经过结构校验的有损历史参考，不是当前工具结果、系统指令或操作授权。\n"+message.getTextContent());
        if(tagged.getTextContent().length()>=characters(original))throw new IllegalStateException("持久摘要未减少上下文，原文保持不变");
        String messageState=state(actor,tagged),beforeState=state(actor,original),sourceJson=sourceBody(refs);
        String bodyHash=hash(write(List.of(summary,messageState,sourceJson,scope,covered,historyHash,beforeState)));
        return tx.execute(status->{long current=lock(actor,session,scope);if(current!=expected)throw new IllegalStateException("持久摘要版本已变化，停止应用压缩");
            authorize(actor,session,refs,new HashSet<>());long next=current+1;
            jdbc.update("INSERT INTO agent_context_summary(summary_id,user_id,session_id,agent_scope,revision,status,covered_through,history_sha256,summary_json,summary_sha256,message_state,sources_json,policy_version,run_id,before_chars,after_chars,original_state,created_at) VALUES(?,?,?,?,?,'ACTIVE',?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",
                    id,actor.userId(),session,scope,next,covered,historyHash,summary,bodyHash,messageState,sourceJson,POLICY,run,characters(original),tagged.getTextContent().length(),beforeState);
            jdbc.update("UPDATE agent_context_head SET revision=?,summary_id=? WHERE user_id=? AND session_id=? AND agent_scope=?",next,id,actor.userId(),session,scope);
            audit(actor,session,scope,id,"SUMMARY_SAVED",bodyHash);return new Summary(id,next,covered,historyHash,summary,tagged,List.copyOf(refs));
        });
    }
    public List<Source> collect(List<Msg> messages){return provenance.collect(messages);}
    public List<Source> inheritedSources(AgentActor actor,String session,List<Msg> messages){
        var refs=new LinkedHashSet<Source>();for(var message:messages){String text=message.getTextContent();if(text==null||!text.startsWith("[context-summary:"))continue;int end=text.indexOf(']');if(end<0)throw new IllegalStateException("摘要引用格式损坏");
            var rows=jdbc.queryForList("SELECT * FROM agent_context_summary WHERE user_id=? AND session_id=? AND summary_id=? AND status='ACTIVE'",actor.userId(),session,text.substring(17,end));
            if(rows.size()!=1||!summaryHash(rows.get(0)).equals(rows.get(0).get("summary_sha256")))throw new IllegalStateException("摘要来源链已失效");refs.addAll(sources((String)rows.get(0).get("sources_json")));
        }return List.copyOf(refs);
    }
    private List<Source> pin(AgentActor actor,String session,List<Source> sources){
        var all=new LinkedHashSet<>(snapshotChildren(actor,session,sources,new HashSet<>(),new HashSet<>()));all.add(new Source("ROLE",actor.role().name(),""));authorize(actor,session,List.copyOf(all),new HashSet<>());
        var plain=all.stream().filter(s->!s.kind().equals("RESEARCH")).toList();var result=new ArrayList<>(data().pin(actor,session,plain));for(var source:all)if(source.kind().equals("RESEARCH")){String digest=jdbc.queryForObject("SELECT content_sha256 FROM agent_research_source WHERE user_id=? AND source_id=? AND expires_at>CURRENT_TIMESTAMP",String.class,actor.userId(),source.resourceId());result.add(new Source("RESEARCH",source.resourceId(),digest));}return List.copyOf(result);
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
                var children=jdbc.queryForList("SELECT session_id,status FROM agent_workbench_item WHERE user_id=? AND item_id=? AND kind='CHILD'",actor.userId(),source.resourceId());
                if(children.size()!=1||!session.equals(children.get(0).get("session_id")))throw new SecurityException("专业来源不属于当前会话");
                var nested=originSources(actor,session,"child:"+source.resourceId(),null);
                if(nested.isEmpty()&&"COMPLETED".equals(children.get(0).get("status")))throw new IllegalStateException("已完成专业任务缺少来源回执");
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
            for(var row:jdbc.queryForList("SELECT sources_json,sources_sha256 FROM agent_context_offload WHERE user_id=? AND session_id=? AND file_id=?",actor.userId(),session,source.resourceId()))authorize(actor,session,checkedSources(row),visited);
        }
        for(var source:sources)if(source.kind().equals("RESEARCH")){
            var found=jdbc.queryForList("SELECT content_sha256 FROM agent_research_source WHERE user_id=? AND source_id=? AND expires_at>CURRENT_TIMESTAMP",actor.userId(),source.resourceId());
            if(found.size()!=1||!source.version().isEmpty()&&!source.version().equals(found.get(0).get("content_sha256")))throw new SecurityException("引用来源已失效");
        }else if(source.kind().equals("CHILD")&&visited.add(source.resourceId())){
            if(visited.size()>32)throw new SecurityException("专业来源关联超出上限");
            var child=jdbc.queryForList("SELECT session_id,payload FROM agent_workbench_item WHERE user_id=? AND item_id=? AND kind='CHILD'",actor.userId(),source.resourceId());
            if(child.size()!=1||!session.equals(child.get(0).get("session_id")))throw new SecurityException("专业来源不属于当前会话");
            authorize(actor,session,originSources(actor,(String)child.get(0).get("session_id"),"child:"+source.resourceId(),null),visited);
        }
    }
    private String summaryHash(Map<String,Object> row){return hash(write(List.of(row.get("summary_json"),row.get("message_state"),row.get("sources_json"),row.get("agent_scope"),((Number)row.get("covered_through")).longValue(),row.get("history_sha256"),Objects.toString(row.get("original_state"),""))));}
    public void validateMessages(AgentActor actor,String session,Set<String> scopes,List<Msg> messages){
        for(var message:messages){String text=message.getTextContent();if(text==null||!text.startsWith("[context-summary:"))continue;
            int end=text.indexOf(']');if(end<0)throw new IllegalStateException("检查点摘要标记损坏");String id=text.substring(17,end);
            var rows=jdbc.queryForList("SELECT * FROM agent_context_summary WHERE user_id=? AND session_id=? AND summary_id=? AND status='ACTIVE'",actor.userId(),session,id);
            if(rows.size()!=1||!scopes.contains(rows.get(0).get("agent_scope"))||!POLICY.equals(rows.get(0).get("policy_version"))||!summaryHash(rows.get(0)).equals(rows.get(0).get("summary_sha256")))throw new IllegalStateException("检查点摘要已失效或损坏，请核对后开始新任务");
            var saved=AgentState.fromJsonString((String)rows.get(0).get("message_state"));if(saved.getContext().size()!=1||!text.equals(saved.getContext().get(0).getTextContent()))throw new IllegalStateException("检查点摘要正文与回执不一致");
            authorize(actor,session,sources((String)rows.get(0).get("sources_json")),new HashSet<>());
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
                jdbc.update("INSERT INTO agent_context_turn(user_id,session_id,message_id,sources_json,sources_sha256) VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE message_id=VALUES(message_id)",actor.userId(),target,pair.targetId(),body,hash(body));
            }
            var offloads=jdbc.queryForList("SELECT * FROM agent_context_offload WHERE user_id=? AND session_id=? ORDER BY id LIMIT 1001",actor.userId(),source);
            if(offloads.size()>1000)throw new IllegalStateException("分支上下文资料超过本次上限，未省略后继续");
            for(var offload:offloads){
                String file=(String)offload.get("file_id");if(!authorized(actor,target,List.of(new Source("FILE",file,(String)offload.get("content_sha256")))))continue;
                var refs=forkSources(actor,source,target,checkedSources(offload));if(refs==null)continue;
                String id=UUID.randomUUID().toString(),body=sourceBody(refs),originalScope=(String)offload.get("agent_scope");
                String inheritedScope="main".equals(originalScope)?"main":"inherited:"+hash(source+":"+originalScope);
                jdbc.update("INSERT INTO agent_context_offload(offload_id,user_id,session_id,agent_scope,call_id,file_id,content_sha256,byte_length,sources_json,sources_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE call_id=VALUES(call_id)",id,actor.userId(),target,inheritedScope,hash("fork:"+offload.get("offload_id")),file,offload.get("content_sha256"),offload.get("byte_length"),body,hash(body));
            }
            var candidates=jdbc.queryForList("SELECT * FROM agent_context_summary WHERE user_id=? AND session_id=? AND agent_scope='main' AND status='ACTIVE' AND covered_through<=? ORDER BY covered_through DESC,revision DESC LIMIT 1",actor.userId(),source,through);
            if(!candidates.isEmpty()){
                var row=candidates.get(0);long covered=((Number)row.get("covered_through")).longValue();
                if(!summaryHash(row).equals(row.get("summary_sha256")))throw new IllegalStateException("分支摘要来源损坏");
                var refs=forkSources(actor,source,target,sources((String)row.get("sources_json")));
                if(refs!=null&&ids.containsKey(covered)&&data().historyDigest(actor,source,covered).equals(row.get("history_sha256"))){
                    long next=ids.get(covered);
                    if(revision(actor,target,"main")==0)save(actor,target,"main","fork-"+row.get("summary_id"),0,next,data().historyDigest(actor,target,next),(String)row.get("summary_json"),new UserMessage((String)row.get("summary_json")),refs,AgentState.fromJsonString((String)row.get("original_state")).getContext());
                }
            }
            audit(actor,target,"main",UUID.nameUUIDFromBytes((source+":"+through).getBytes(StandardCharsets.UTF_8)).toString(),"CONTEXT_FORKED",hash(source+":"+through));
        });
    }
    public void recordResult(AgentActor actor,String session,String scope,String task,String run,String callKey,String tool,Map<String,Object> input,ToolResultBlock result){
        // The workbench binds tool/input/result to this call key. Reusing its completed result
        // must also reuse the original child-source snapshot, not the child's later conversations.
        var existing=jdbc.queryForList("SELECT logical_task_id,sources_json,sources_sha256 FROM agent_context_origin WHERE user_id=? AND session_id=? AND agent_scope=? AND call_key=?",actor.userId(),session,scope,callKey);
        if(!existing.isEmpty()){
            if(existing.size()!=1||!task.equals(existing.get(0).get("logical_task_id")))throw new IllegalStateException("工具来源执行归属冲突");
            authorize(actor,session,checkedSources(existing.get(0)),new HashSet<>());return;
        }
        var refs=provenance.tool(tool,input==null?Map.of():input,result);
        recordOrigin(actor,session,scope,task,run,callKey,pin(actor,session,refs));
    }
    public void recordSeed(AgentActor actor,String session,String scope,String task,String run,List<Source> sources){recordOrigin(actor,session,scope,task,run,hash("seed:"+task),pin(actor,session,sources));}
    private void recordOrigin(AgentActor actor,String session,String scope,String task,String run,String callKey,List<Source> refs){
        String body=sourceBody(refs),digest=hash(body);
        tx.executeWithoutResult(status->{var old=jdbc.queryForList("SELECT sources_sha256 FROM agent_context_origin WHERE user_id=? AND session_id=? AND agent_scope=? AND call_key=?",actor.userId(),session,scope,callKey);
            if(!old.isEmpty()){if(!digest.equals(old.get(0).get("sources_sha256")))throw new IllegalStateException("工具来源回执不一致");return;}
            jdbc.update("INSERT INTO agent_context_origin(user_id,session_id,agent_scope,call_key,logical_task_id,run_id,sources_json,sources_sha256) VALUES(?,?,?,?,?,?,?,?)",actor.userId(),session,scope,callKey,task,run,body,digest);
            audit(actor,session,scope,UUID.nameUUIDFromBytes(callKey.getBytes(StandardCharsets.UTF_8)).toString(),"ORIGIN_SAVED",digest);
        });
    }
    private List<Source> originSources(AgentActor actor,String session,String scope,String task){
        var args=new ArrayList<Object>(List.of(actor.userId(),session));String where="user_id=? AND session_id=?";if(scope!=null){where+=" AND agent_scope=?";args.add(scope);}if(task!=null){where+=" AND logical_task_id=?";args.add(task);}
        var rows=jdbc.queryForList("SELECT sources_json,sources_sha256 FROM agent_context_origin WHERE "+where+" LIMIT 513",args.toArray());
        if(rows.size()>512)throw new IllegalStateException("工具来源历史超过本次读取上限，未省略后继续");
        var refs=new LinkedHashSet<Source>();for(var row:rows){String body=(String)row.get("sources_json");if(!hash(body).equals(row.get("sources_sha256")))throw new IllegalStateException("工具来源回执损坏");refs.addAll(sources(body));if(refs.size()>2000)throw new IllegalStateException("工具来源集合超过本次上限");}return List.copyOf(refs);
    }
    public void turnSaved(AgentActor actor,String session,String task,long message){var refs=pin(actor,session,originSources(actor,session,null,task));String body=sourceBody(refs);tx.executeWithoutResult(status->{lock(actor,session,"turn-links");var prior=jdbc.queryForList("SELECT sources_sha256 FROM agent_context_turn WHERE user_id=? AND session_id=? AND message_id=?",actor.userId(),session,message);if(!prior.isEmpty()){if(!hash(body).equals(prior.get(0).get("sources_sha256")))throw new IllegalStateException("历史轮次来源编号已绑定其他内容");return;}jdbc.update("INSERT INTO agent_context_turn(user_id,session_id,message_id,sources_json,sources_sha256) VALUES(?,?,?,?,?)",actor.userId(),session,message,body,hash(body));audit(actor,session,"main",UUID.nameUUIDFromBytes((session+":"+message).getBytes(StandardCharsets.UTF_8)).toString(),"TURN_LINKED",hash(body));});}
    public List<Source> turnSources(AgentActor actor,String session,long message){var rows=jdbc.queryForList("SELECT sources_json,sources_sha256 FROM agent_context_turn WHERE user_id=? AND session_id=? AND message_id=?",actor.userId(),session,message);if(rows.isEmpty())return null;String body=(String)rows.get(0).get("sources_json");if(!hash(body).equals(rows.get(0).get("sources_sha256")))throw new IllegalStateException("历史来源回执损坏");return sources(body);}
    public ToolResultBlock offload(AgentActor actor,String session,String scope,String key,ToolResultBlock result){
        if(!offloadEnabled||result.getState()!=null&&Set.of("ERROR","FAILED").contains(result.getState().name())||result.getOutput().stream().anyMatch(block->!(block instanceof TextBlock)))return result;
        String text=ContextProvenance.text(result);byte[] bytes=text.getBytes(StandardCharsets.UTF_8);if(bytes.length<=16384)return result;
        if(bytes.length>2097152)throw new IllegalStateException("工具结果超过受控卸载上限，未截断后继续");
        var origins=jdbc.queryForList("SELECT sources_json,sources_sha256 FROM agent_context_origin WHERE user_id=? AND session_id=? AND agent_scope=? AND call_key=?",actor.userId(),session,scope,key);
        if(origins.size()!=1)throw new IllegalStateException("工具来源回执缺失，未生成缺少授权依据的卸载资料");
        var references=new ArrayList<>(checkedSources(origins.get(0)));
        var refs=pin(actor,session,references);String digest=hash(text);
        return tx.execute(status->{
            var rows=jdbc.queryForList("SELECT file_id,content_sha256 FROM agent_context_offload WHERE user_id=? AND session_id=? AND agent_scope=? AND call_id=?",actor.userId(),session,scope,key);
            String fileId;if(!rows.isEmpty()){if(!digest.equals(rows.get(0).get("content_sha256")))throw new IllegalStateException("卸载结果摘要冲突");fileId=(String)rows.get(0).get("file_id");}
            else{var file=data().saveContextFile(actor,session,hash(scope+":"+key+":"+digest),text);fileId=file.id();String id=UUID.randomUUID().toString();
                String body=sourceBody(refs);jdbc.update("INSERT INTO agent_context_offload(offload_id,user_id,session_id,agent_scope,call_id,file_id,content_sha256,byte_length,sources_json,sources_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",id,actor.userId(),session,scope,key,fileId,digest,bytes.length,body,hash(body));audit(actor,session,scope,id,"TOOL_RESULT_OFFLOADED",digest);}
            data().authorize(actor,session,List.of(new Source("FILE",fileId,digest)));
            String excerpt=text.codePoints().limit(1200).collect(StringBuilder::new,StringBuilder::appendCodePoint,StringBuilder::append).toString();
            return ToolResultBlock.text("[已完成工具结果的有界摘录，不代表完整内容]\n"+excerpt+"\n[完整结果已保存为当前 Agent 的私有上下文资料]\nfileId="+fileId+"\nsha256="+digest+"\nbytes="+bytes.length+"\n需要后续内容时使用 read_context_file，必须提供 fileId、sha256 和 offset；不能从摘录推断完整结论。");
        });
    }
    public AgentContextDataApi.Slice read(AgentActor actor,String session,String scope,String id,String sha,int offset,int limit){
        var rows=jdbc.queryForList("SELECT * FROM agent_context_offload WHERE user_id=? AND session_id=? AND agent_scope=? AND file_id=?",actor.userId(),session,scope,id);
        if(rows.size()!=1||!sha.equals(rows.get(0).get("content_sha256")))throw new SecurityException("此上下文文件不属于当前 Agent 或摘要不匹配");authorize(actor,session,checkedSources(rows.get(0)),new HashSet<>());return data().readContextFile(actor,session,id,sha,offset,limit);
    }
    public List<AgentWorkbenchApi.Item> views(AgentActor actor,String session){data().authorize(actor,session,List.of());var result=new ArrayList<AgentWorkbenchApi.Item>();
        for(var row:jdbc.queryForList("SELECT s.summary_id,s.agent_scope,s.revision,s.status,s.covered_through,s.before_chars,s.after_chars,s.created_at FROM agent_context_head h JOIN agent_context_summary s ON s.summary_id=h.summary_id WHERE h.user_id=? AND h.session_id=? ORDER BY s.id DESC LIMIT 20",actor.userId(),session)){
            var fields=new LinkedHashMap<String,Object>();fields.put("title","持久上下文摘要");fields.put("phase","PERSISTED");fields.put("agentScope",row.get("agent_scope"));fields.put("coveredThrough",row.get("covered_through"));fields.put("beforeChars",row.get("before_chars"));fields.put("afterChars",row.get("after_chars"));fields.put("basis","CHARACTER_ESTIMATE");fields.put("text","摘要仅作为历史参考，权限变化时重新核对；原始聊天和工具回执保留");
            result.add(new AgentWorkbenchApi.Item((String)row.get("summary_id"),"CONTEXT",(String)row.get("status"),((Number)row.get("revision")).longValue(),fields,row.get("created_at").toString()));
        }
        for(var row:jdbc.queryForList("SELECT offload_id,file_id,agent_scope,byte_length,content_sha256,created_at FROM agent_context_offload WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT 30",actor.userId(),session))result.add(new AgentWorkbenchApi.Item((String)row.get("offload_id"),"CONTEXT","COMPLETED",0,Map.of("title","工具上下文资料","phase","OFFLOADED","agentScope",row.get("agent_scope"),"fileId",row.get("file_id"),"byteLength",row.get("byte_length"),"sha256",row.get("content_sha256"),"text","模型仅接收摘录，可通过受控工具分段读取完整结果"),row.get("created_at").toString()));return List.copyOf(result);
    }
    private List<Source> sources(String body){try{
        if(body==null||body.length()>1048576)throw new IllegalArgumentException();
        List<Source> refs=json.readValue(body,new TypeReference<List<Source>>(){});
        if(refs==null||refs.size()>2000||refs.stream().anyMatch(source->source==null||source.kind()==null||!Set.of("ROLE","FILE","TASK","REPORT","DEVICE","ALERT","MODEL","RESEARCH","CHILD","BUSINESS_FILE","BUSINESS_IMAGE").contains(source.kind())||source.resourceId()==null||source.resourceId().isBlank()||source.resourceId().length()>256||source.version()==null||source.version().length()>256))throw new IllegalArgumentException();
        return List.copyOf(refs);
    }catch(Exception invalid){throw new IllegalStateException("上下文来源格式或资源边界无效");}}
    private String sourceBody(List<Source> refs){String body=write(refs);sources(body);return body;}
    private List<Source> checkedSources(Map<String,Object> row){String body=(String)row.get("sources_json");if(!hash(body).equals(row.get("sources_sha256")))throw new IllegalStateException("上下文来源回执损坏");return sources(body);}
    private String state(AgentActor actor,Msg message){return state(actor,List.of(message));}
    private String state(AgentActor actor,List<Msg> messages){return AgentState.builder().userId(Long.toString(actor.userId())).sessionId("private-context").context(messages).build().toJson();}
    static long characters(List<Msg> messages){return messages.stream().flatMap(m->m.getContent().stream()).mapToLong(b->ContextProvenance.text(b).length()).sum();}
    String write(Object value){try{return json.writeValueAsString(value);}catch(Exception invalid){throw new IllegalStateException("上下文无法序列化");}}
    static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception invalid){throw new IllegalStateException(invalid);}}
    private void audit(AgentActor actor,String session,String scope,String id,String action,String digest){jdbc.update("INSERT INTO agent_context_audit(user_id,session_id,agent_scope,resource_id,action,content_sha256,created_at) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",actor.userId(),session,scope,id,action,digest);}
}
