package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.*;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.task.TaskExecutor;
import org.springframework.security.concurrent.DelegatingSecurityContextRunnable;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

/** 保留主站会话协议；没有旧路由、图节点、断点恢复或独立模型客户端。 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AgentScopeChatServiceImpl implements ChatConversationService, AgentChatSessionApi {
    private final ChatSessionService sessions;
    private final ObjectProvider<AgentConversationApi> agents;
    private final RagKnowledgeService knowledge;
    private final Mem0Client memory;
    private final TaskExecutor taskExecutor;
    private final ChatAssistantProperties properties;
    private final ObjectMapper json;
    private final Set<String> active = ConcurrentHashMap.newKeySet();
    private final Map<Long, Deque<Long>> rateWindows = new ConcurrentHashMap<>();
    private ObjectProvider<AgentWorkbenchApi> workbench;
    @org.springframework.beans.factory.annotation.Autowired public void setWorkbench(ObjectProvider<AgentWorkbenchApi> workbench){this.workbench=workbench;}

    private AgentActor actor(String username) {
        var auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !auth.isAuthenticated() || !(auth.getPrincipal() instanceof TenantPrincipal principal))
            throw new BusinessException(401, "请使用有效账号登录");
        if (!principal.username().equals(username)) throw new BusinessException(403, "登录身份与请求用户不一致");
        var roles = auth.getAuthorities().stream().map(a -> a.getAuthority()).toList();
        AgentActor.Role role = roles.contains("ROLE_SUPERVISOR") ? AgentActor.Role.SUPERVISOR
                : roles.contains("ROLE_INSPECTOR") ? AgentActor.Role.INSPECTOR : null;
        if (role == null) throw new BusinessException(403, "当前账号没有检测助手权限");
        return new AgentActor(principal.userId(), principal.username(), role);
    }
    private AgentConversationApi api() {
        var api = agents.getIfAvailable();
        if (!Boolean.TRUE.equals(properties.getEnabled()) || api == null) throw new BusinessException(503, "AgentScope 助手尚未启用");
        return api;
    }
    @Override public AgentConversationApi.Status status(String username) {
        actor(username);
        var api = agents.getIfAvailable();
        return api == null || !Boolean.TRUE.equals(properties.getEnabled())
                ? new AgentConversationApi.Status("AgentScope", "DISABLED", null) : api.status();
    }
    @Override public ChatMessageResponse handleUserMessage(String username, ChatSendMessageRequest request) {
        return execute(actor(username), request, event -> {}, new AtomicReference<>(), new AtomicBoolean());
    }
    @Override public ChatMessageResponse handleQueuedMessage(String username,ChatSendMessageRequest request,String inputId,String entryPoint){
        return execute(actor(username),request,event->{},new AtomicReference<>(),new AtomicBoolean(),"AGUI".equals(entryPoint)?inputId:null,event->{});
    }
    @Override public SseEmitter streamUserMessage(String username, ChatSendMessageRequest request) {
        var actor = actor(username); api();
        var emitter = new SseEmitter(190_000L);
        var run = new AtomicReference<AgentConversationApi.Run>();
        var disconnected = new AtomicBoolean();
        Runnable cancel = () -> { disconnected.set(true); var current = run.get(); if (current != null) current.cancel().run(); };
        emitter.onCompletion(cancel); emitter.onTimeout(cancel); emitter.onError(error -> cancel.run());
        Runnable task = () -> {
            try {
                send(emitter, "connected", ChatStreamEvent.status(request.getSessionId(), "已连接 AgentScope"));
                var response = execute(actor, request, event -> send(emitter, event.getType(), event), run, disconnected);
                if (!disconnected.get()) send(emitter, "done", ChatStreamEvent.builder().type("done").sessionId(response.getSessionId()).messageResponse(response).build());
                emitter.complete();
            } catch (Exception error) {
                log.warn("AgentScope 聊天失败：errorType={}", error.getClass().getSimpleName());
                if (!disconnected.get()) {
                    try { send(emitter, "error", ChatStreamEvent.builder().type("error").sessionId(request.getSessionId()).message("智能助手执行失败，请稍后重试").build()); }
                    catch (RuntimeException ignored) {}
                }
                emitter.complete();
            }
        };
        taskExecutor.execute(new DelegatingSecurityContextRunnable(task, SecurityContextHolder.getContext()));
        return emitter;
    }
    private ChatMessageResponse execute(AgentActor actor, ChatSendMessageRequest request, Consumer<ChatStreamEvent> output,
            AtomicReference<AgentConversationApi.Run> holder, AtomicBoolean disconnected) {
        return execute(actor, request, output, holder, disconnected, null, event -> {});
    }
    @Override public AgentChatSessionApi.Run start(AgentActor supplied, String sessionId, String requestId,
                                                   String question, Consumer<AgentConversationApi.Event> events) {
        if (supplied == null || !supplied.equals(actor(supplied.username())))
            throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.FORBIDDEN, "登录身份不一致");
        api();
        if (sessionId == null || !sessionId.matches("[A-Za-z0-9_.-]{1,128}") || requestId == null
                || !requestId.matches("[A-Za-z0-9_-]{1,128}") || question == null || question.isBlank() || question.length() > 8000 || events == null)
            throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST, "会话请求格式不正确");
        try { sessions.verifySessionOwner(supplied.username(), sessionId); }
        catch (BusinessException error) { throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.valueOf(error.getCode()), error.getMessage()); }
        api().checkRequest(supplied, "AGUI", requestId);
        var request = new ChatSendMessageRequest(); request.setSessionId(sessionId); request.setContent(question);
        var result = new CompletableFuture<AgentChatSessionApi.Reply>();
        var holder = new AtomicReference<AgentConversationApi.Run>();
        var disconnected = new AtomicBoolean();
        Runnable cancel = () -> { disconnected.set(true); var run = holder.get(); if (run != null) run.cancel().run(); result.cancel(true); };
        taskExecutor.execute(new DelegatingSecurityContextRunnable(() -> {
            try {
                var saved = execute(supplied, request, event -> {}, holder, disconnected, requestId, events);
                String text = saved.getContent(); java.util.List<AgentCards.Reference> cards = java.util.List.of();
                if (AgentCards.MESSAGE_TYPE.equals(saved.getMessageType())) {
                    var envelope = json.readValue(text, AgentCards.Envelope.class); text = envelope.text(); cards = envelope.cards();
                }
                var run = holder.get(); result.complete(new AgentChatSessionApi.Reply(text, run == null ? null : run.runId(), cards));
            } catch (Exception error) {
                log.warn("持久 AG-UI 会话执行失败：errorType={}", error.getClass().getSimpleName());
                result.completeExceptionally(new IllegalStateException("智能助手执行失败，请稍后重试"));
            }
        }, SecurityContextHolder.getContext()));
        return new AgentChatSessionApi.Run(result, cancel);
    }
    private ChatMessageResponse execute(AgentActor actor, ChatSendMessageRequest request, Consumer<ChatStreamEvent> output,
            AtomicReference<AgentConversationApi.Run> holder, AtomicBoolean disconnected, String requestId,
            Consumer<AgentConversationApi.Event> agentEvents) {
        var api = api();
        if (request == null || request.getContent() == null || request.getContent().isBlank() || request.getContent().length() > 8000)
            throw new BusinessException(400, "消息长度必须在 1 到 8000 字符之间");
        if (request.getSessionId() == null || request.getSessionId().isBlank()) request.setSessionId(sessions.getOrCreateActiveSession(actor.username()).getSessionId());
        String sessionId = request.getSessionId();
        sessions.verifySessionOwner(actor.username(), sessionId);
        String key = actor.userId() + ":" + sessionId;
        if (!active.add(key)) throw new BusinessException(409, "当前会话仍在处理上一轮请求");
        var tenant = new TenantContext(actor.userId(), actor.username());
        var trace = new CopyOnWriteArrayList<AgentConversationApi.Event>();
        String runId = UUID.randomUUID().toString();
        String state = "ERROR";
        try {
            enforceRate(actor.userId());
            if (disconnected.get()) throw new CancellationException();
            var stored = sessions.listMessages(actor.username(), sessionId);
            int keep = Math.min(38, Math.max(0, properties.getMaxHistoryMessages()));
            var history = new ArrayList<AgentConversationApi.Message>();
            var textHistory = stored.stream().map(this::textHistory).filter(Objects::nonNull).filter(message -> "user".equals(message.getRole())
                    || "assistant".equals(message.getRole()) && (message.getMessageType() == null || "TEXT".equals(message.getMessageType())))
                    .filter(message -> message.getContent() != null && message.getContent().length() <= 8000).toList();
            for (var message : textHistory.subList(Math.max(0, textHistory.size() - keep), textHistory.size()))
                history.add(new AgentConversationApi.Message(message.getRole(), message.getContent()));
            history.add(new AgentConversationApi.Message("user", request.getContent()));
            output.accept(ChatStreamEvent.status(sessionId, "AgentScope 正在检索并处理问题"));
            boolean command=request.getContent().stripLeading().startsWith("/");
            String context = command?"":Objects.toString(knowledge.retrieveContext(request.getContent(),new com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity(actor.userId(),actor.username(),false)), "");
            if(!command){var memories = memory.searchAccountMemories(tenant, sessionId, request.getContent(), 10);
                if (memories != null && !memories.isEmpty()) {
                    String personal=Objects.toString(memory.formatMemoriesAsContext(memories),"");
                    if(personal.length()>2000)personal=personal.substring(0,2000);
                    int remaining=6000-personal.length()-1;
                    if(context.length()>remaining)context=context.substring(0,remaining);
                    context+="\n"+personal;
                }
            }
            if (context.length() > 6000) context = context.substring(0, 6000);
            Consumer<AgentConversationApi.Event> consume = event -> {
                if (disconnected.get()) throw new IllegalStateException("聊天通道已关闭");
                agentEvents.accept(event);
                if ("TEXT_CHUNK".equals(event.type())) output.accept(ChatStreamEvent.builder().type("chunk").sessionId(sessionId).content(event.text()).build());
                else if (trace.size() < 200) trace.add(event);
            };
            var run = requestId == null ? api.start(actor, sessionId, history, context, consume)
                    : api.start(actor, sessionId, history, context, consume, "AGUI", requestId);
            holder.set(run); if (run.runId() != null) runId = run.runId(); if (disconnected.get()) run.cancel().run();
            if (disconnected.get()) throw new CancellationException();
            sessions.appendUserMessage(tenant, sessionId, request.getContent());
            String reply = run.result().get(Math.max(185,api.maxRunSeconds()+5), TimeUnit.SECONDS);
            if (disconnected.get()) throw new CancellationException();
            var cards = run.cards().get();
            String content = reply, messageType = "TEXT";
            if (cards != null && !cards.isEmpty()) {
                try { content = json.writeValueAsString(new AgentCards.Envelope(1,reply,run.runId(),cards)); messageType = AgentCards.MESSAGE_TYPE; }
                catch (Exception error) { log.warn("卡片编码失败，保留文字回答：errorType={}",error.getClass().getSimpleName()); }
            }
            var saved = sessions.appendAssistantMessage(tenant, sessionId, content, messageType, "AGENTSCOPE", null);
            if(workbench!=null&&workbench.getIfAvailable()!=null&&saved.getId()!=null)workbench.getObject().turnSaved(actor,sessionId,saved.getId());
            try {
                // Personal facts come from the user's message. Generated answers and retrieved
                // business context must not become assertions attributed to the user.
                if(!command)memory.addMemoryAsync(tenant, sessionId, request.getContent(),
                        Map.of("source", "agentscope-chat", "timestamp", System.currentTimeMillis(),"turn_id",saved.getId()!=null?saved.getId():run.runId()));
            } catch (RuntimeException error) { log.warn("对话记忆保存失败：errorType={}", error.getClass().getSimpleName()); }
            state = "COMPLETED";
            return saved;
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt(); state = "CANCELLED"; throw new BusinessException("助手请求已取消");
        } catch (CancellationException error) {
            state = "CANCELLED"; throw new BusinessException("助手请求已取消");
        } catch (ExecutionException | TimeoutException error) {
            if(error.getCause() instanceof AgentConversationApi.UnverifiedAnswerException unverified)
                throw new BusinessException(unverified.getMessage());
            throw new BusinessException("AgentScope 执行失败，请稍后重试");
        } finally {
            var run = holder.get(); if (run != null && !run.result().isDone()) run.cancel().run();
            if (!trace.isEmpty()) try {
                sessions.saveExecutionTrace(tenant, sessionId, json.writeValueAsString(Map.of("framework", "AgentScope", "runId", runId,
                        "status", state, "updatedAt", LocalDateTime.now().toString(), "events", trace)));
            } catch (Exception error) { log.warn("会话执行轨迹保存失败：errorType={}", error.getClass().getSimpleName()); }
            active.remove(key);
        }
    }
    private ChatMessageResponse textHistory(ChatMessageResponse message) {
        if (!AgentCards.MESSAGE_TYPE.equals(message.getMessageType())) return message;
        try {
            var envelope=json.readValue(message.getContent(),AgentCards.Envelope.class);
            var text=new ChatMessageResponse();text.setRole(message.getRole());text.setMessageType("TEXT");text.setContent(envelope.text());return text;
        } catch(Exception ignored) {return null;}
    }
    @Override public ChatMessageResponse confirmAction(String username, ChatConfirmActionRequest request) {
        var actor = actor(username); var tenant = new TenantContext(actor.userId(), actor.username());
        sessions.verifySessionOwner(username, request.getSessionId());
        if (request.isConfirmed()) throw new BusinessException(410, "旧版 Agent 动作已停用，请到业务页面执行操作");
        sessions.getPendingAction(tenant, request.getSessionId(), request.getActionId());
        if (!sessions.transitionPendingAction(tenant, request.getSessionId(), request.getActionId(), "PENDING", "CANCELLED", null))
            throw new BusinessException(409, "此动作已处理");
        return sessions.appendAssistantMessage(tenant, request.getSessionId(), "已取消旧版待确认动作", "TEXT", "AGENTSCOPE", null);
    }
    private void enforceRate(long userId) {
        long now = System.currentTimeMillis(); var window = rateWindows.computeIfAbsent(userId, ignored -> new ArrayDeque<>());
        synchronized (window) {
            while (!window.isEmpty() && now - window.peekFirst() >= 60_000) window.removeFirst();
            if (window.size() >= Math.max(1, properties.getMaxRequestsPerMinute())) throw new BusinessException(429, "聊天请求过于频繁，请稍后再试");
            window.addLast(now);
        }
    }
    private void send(SseEmitter emitter, String event, Object data) {
        try { emitter.send(SseEmitter.event().name(event).data(data)); }
        catch (Exception error) { throw new IllegalStateException("聊天通道已关闭"); }
    }
}
