package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import io.agentscope.core.agui.model.RunAgentInput;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** AG-UI 只适配协议；历史、记忆、持久化和执行共用主站的服务端会话门面。 */
@RestController
@ConditionalOnProperty(prefix="agentscope.ai",name="enabled",havingValue="true")
public class RoleAgentController {
    private final RoleAgentFactory factory;
    private final AgentChatSessionApi sessions;
    private com.ruanzhu.doorhandle.module.ai.ui.A2uiService surfaces;
    @org.springframework.beans.factory.annotation.Autowired(required=false)
    public void setSurfaces(com.ruanzhu.doorhandle.module.ai.ui.A2uiService surfaces){this.surfaces=surfaces;}
    public RoleAgentController(RoleAgentFactory factory) { this(factory,null); }
    @org.springframework.beans.factory.annotation.Autowired
    public RoleAgentController(RoleAgentFactory factory,AgentChatSessionApi sessions) { this.factory=factory;this.sessions=sessions; }
    @ModelAttribute
    public void preventPrivateCaching(jakarta.servlet.http.HttpServletResponse response) { response.setHeader("Cache-Control","no-store"); }
    @ExceptionHandler(org.springframework.security.access.AccessDeniedException.class)
    public org.springframework.http.ResponseEntity<?> forbidden() {
        return org.springframework.http.ResponseEntity.status(HttpStatus.FORBIDDEN).body(Map.of("message","当前登录身份无权访问该助手"));
    }
    @ExceptionHandler(ResponseStatusException.class)
    public org.springframework.http.ResponseEntity<?> invalidRequest(ResponseStatusException error) {
        return org.springframework.http.ResponseEntity.status(error.getStatusCode()).body(Map.of("message",error.getReason()==null?"请求无效":error.getReason()));
    }
    @GetMapping("${agentscope.agui.path-prefix:/agui}/catalog")
    public Map<String,Object> catalog(Authentication auth) {
        AgentActor actor=AgentIdentity.from(auth);
        return Map.ofEntries(Map.entry("mainAgent",RoleAgentCatalog.mainId(actor)),Map.entry("role",actor.role()),Map.entry("agents",factory.definitions(actor)),
                Map.entry("mode",(factory.confirmationEnabled()&&actor.supervisor()||factory.retryEnabled())?"CONFIRMABLE":factory.reportDraftsEnabled()||factory.evolutionEnabled()||factory.mcpEnabled()?"DRAFTS":"READ_ONLY"),
                Map.entry("reportsEnabled",factory.reportsEnabled()),Map.entry("reportDraftsEnabled",factory.reportDraftsEnabled()),
                Map.entry("skillEvolutionEnabled",factory.evolutionEnabled()),Map.entry("localMcpEnabled",factory.mcpEnabled()),
                Map.entry("sessionHistory","SERVER"),Map.entry("memoryScope","ACCOUNT"),
                Map.entry("a2ui",Map.of("version",com.ruanzhu.doorhandle.module.ai.ui.A2uiService.VERSION,"catalogId",com.ruanzhu.doorhandle.module.ai.ui.A2uiService.CATALOG,"enabled",surfaces!=null)));
    }
    @PostMapping(value="${agentscope.agui.path-prefix:/agui}/run",produces="text/event-stream")
    public SseEmitter run(@RequestBody RunAgentInput input,@RequestHeader(value="${agentscope.agui.agent-id-header:X-Agent-Id}",required=false)String header,Authentication auth) {
        return execute(input,header,null,auth);
    }
    @PostMapping(value="${agentscope.agui.path-prefix:/agui}/run/{agentId}",produces="text/event-stream")
    public SseEmitter runWithAgent(@PathVariable String agentId,@RequestBody RunAgentInput input,@RequestHeader(value="${agentscope.agui.agent-id-header:X-Agent-Id}",required=false)String header,Authentication auth) {
        return execute(input,header,agentId,auth);
    }
    private SseEmitter execute(RunAgentInput input,String header,String path,Authentication auth) {
        AgentActor actor=AgentIdentity.from(auth);validate(input);
        String requested=path!=null?path:header!=null?header:input.getForwardedProp("agentId") instanceof String id?id:null;
        factory.resolveMainId(actor,requested);
        if(sessions==null)throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"持久会话服务尚未启用");
        var emitter=new SseEmitter(190_000L);var closed=new AtomicBoolean();var started=new AtomicBoolean();var emitted=new AtomicBoolean();
        var holder=new AtomicReference<AgentChatSessionApi.Run>();String messageId="reply-"+UUID.randomUUID();
        Runnable cancel=()->{if(closed.compareAndSet(false,true)){var run=holder.get();if(run!=null&&!run.result().isDone())run.cancel().run();}};
        emitter.onCompletion(cancel);emitter.onTimeout(()->{cancel.run();emitter.complete();});emitter.onError(error->cancel.run());
        try {
            var last=input.getMessages().get(input.getMessages().size()-1);
            var run=sessions.start(actor,input.getThreadId(),input.getRunId(),last.getTextContent(),event->{
                synchronized(emitter){
                if(closed.get())throw new IllegalStateException("聊天通道已关闭");
                if(started.compareAndSet(false,true))send(emitter,Map.of("type","RUN_STARTED","threadId",input.getThreadId(),"runId",input.getRunId()));
                if("TEXT_CHUNK".equals(event.type())&&event.text()!=null&&!event.text().isEmpty()){
                    if(emitted.compareAndSet(false,true))send(emitter,Map.of("type","TEXT_MESSAGE_START","messageId",messageId,"role","assistant"));
                    send(emitter,Map.of("type","TEXT_MESSAGE_CONTENT","messageId",messageId,"delta",event.text()));
                }
                if(event.callId()!=null&&event.tool()!=null){
                    if("TOOL_STARTED".equals(event.type())){
                        send(emitter,Map.of("type","TOOL_CALL_START","toolCallId",event.callId(),"toolCallName",event.tool()));
                        send(emitter,Map.of("type","TOOL_CALL_END","toolCallId",event.callId()));
                    }else if("TOOL_COMPLETED".equals(event.type()))send(emitter,Map.of("type","TOOL_CALL_RESULT","toolCallId",event.callId(),"messageId","tool-"+event.callId(),"role","tool","content","工具已返回；业务结论以结果为准"));
                    else if(java.util.Set.of("TOOL_ERROR","TOOL_CANCELLED").contains(event.type()))send(emitter,Map.of("type","CUSTOM","name","doorhandle.tool-status.v1","value",Map.of("toolCallId",event.callId(),"status","TOOL_ERROR".equals(event.type())?"failed":"cancelled")));
                }
                }
            });
            holder.set(run);if(closed.get())run.cancel().run();
            run.result().whenComplete((reply,error)->{
                if(closed.get())return;
                try {
                    if(error!=null)send(emitter,Map.of("type","RUN_ERROR","message","智能助手执行失败，请稍后重试"));
                    else {
                        if(started.compareAndSet(false,true))send(emitter,Map.of("type","RUN_STARTED","threadId",input.getThreadId(),"runId",input.getRunId()));
                        if(emitted.compareAndSet(false,true)){
                            send(emitter,Map.of("type","TEXT_MESSAGE_START","messageId",messageId,"role","assistant"));
                            send(emitter,Map.of("type","TEXT_MESSAGE_CONTENT","messageId",messageId,"delta",reply.text()));
                        }
                        send(emitter,Map.of("type","TEXT_MESSAGE_END","messageId",messageId));
                        if(reply.runId()!=null){var metadata=new java.util.LinkedHashMap<String,Object>();metadata.put("runId",reply.runId());if(reply.messageId()!=null)metadata.put("messageId",reply.messageId());send(emitter,Map.of("type","CUSTOM","name","doorhandle.execution.v1","value",metadata));}
                        if(reply.cards()!=null&&!reply.cards().isEmpty()){
                            send(emitter,Map.of("type","CUSTOM","name","doorhandle.business-cards.v1","value",Map.of("version",1,"runId",reply.runId()==null?"":reply.runId(),"cards",reply.cards())));
                            if(surfaces!=null)try{
                                var projected=surfaces.resolve(actor,new com.ruanzhu.doorhandle.module.ai.ui.A2uiService.Query(input.getThreadId(),reply.cards()));
                                for(var envelope:(java.util.List<?>)projected.get("messages"))send(emitter,Map.of("type","CUSTOM","name",com.ruanzhu.doorhandle.module.ai.ui.A2uiService.EVENT,"value",envelope));
                            }catch(RuntimeException unavailable){send(emitter,Map.of("type","CUSTOM","name","doorhandle.ui-unavailable.v1","value",Map.of("message","动态界面暂不可用，可在业务结果中重新读取")));}
                        }
                        send(emitter,Map.of("type","RUN_FINISHED","threadId",input.getThreadId(),"runId",input.getRunId()));
                    }
                    emitter.complete();
                }catch(RuntimeException failure){cancel.run();emitter.complete();}
            });
            return emitter;
        }catch(RuntimeException error){cancel.run();throw error;}
    }
    private static void send(SseEmitter emitter,Object data){try{emitter.send(SseEmitter.event().data(data));}catch(Exception error){throw new IllegalStateException("聊天通道已关闭");}}
    static void validate(RunAgentInput input){
        if(input==null||input.getThreadId()==null||!input.getThreadId().matches("[A-Za-z0-9_.-]{1,128}")||input.getRunId()==null||!input.getRunId().matches("[A-Za-z0-9_-]{1,128}"))throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"会话与运行编号格式不正确");
        if(input.hasTools()||input.hasState()||input.hasContext()||input.hasResume())throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"不接受客户端工具、状态、上下文或恢复指令");
        if(!input.hasMessages()||input.getMessages().size()>40)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"消息数必须在 1 到 40 之间");
        for(var message:input.getMessages())if(message==null||!("user".equals(message.getRole())||"assistant".equals(message.getRole()))||message.hasBlocks()||message.hasToolCalls()||message.getToolCallId()!=null||message.getTextContent()==null||message.getTextContent().length()>8000)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"仅允许用户和助手文本消息；历史由服务端读取");
        var last=input.getMessages().get(input.getMessages().size()-1);if(!"user".equals(last.getRole())||last.getTextContent().isBlank())throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"最后一条必须是用户问题");
    }
}
