package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.agui.adapter.AguiAdapterConfig;
import io.agentscope.core.agui.model.RunAgentInput;
import io.agentscope.core.agui.processor.AgentResolver;
import io.agentscope.core.agui.processor.AguiRequestProcessor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;
import reactor.core.scheduler.Schedulers;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** 在进入异步 AG-UI 执行之前捕获身份；每轮新建 Agent，不共享跨用户模型记忆。 */
@RestController
@ConditionalOnProperty(prefix = "agentscope.ai", name = "enabled", havingValue = "true")
public class RoleAgentController {
    private final RoleAgentFactory factory;
    private final Map<String, Boolean> activeSessions = new ConcurrentHashMap<>();
    public RoleAgentController(RoleAgentFactory factory) { this.factory = factory; }

    @ExceptionHandler(org.springframework.security.access.AccessDeniedException.class)
    public org.springframework.http.ResponseEntity<?> forbidden() {
        return org.springframework.http.ResponseEntity.status(HttpStatus.FORBIDDEN)
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(Map.of("message", "当前登录身份无权访问该助手"));
    }

    @ExceptionHandler(ResponseStatusException.class)
    public org.springframework.http.ResponseEntity<?> invalidRequest(ResponseStatusException error) {
        return org.springframework.http.ResponseEntity.status(error.getStatusCode())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON)
                .body(Map.of("message", error.getReason() == null ? "请求无效" : error.getReason()));
    }

    @GetMapping("${agentscope.agui.path-prefix:/agui}/catalog")
    public Map<String, Object> catalog(Authentication auth) {
        AgentActor actor = AgentIdentity.from(auth);
        return Map.of("mainAgent", RoleAgentCatalog.mainId(actor), "role", actor.role(),
                "agents", RoleAgentCatalog.specialists(actor), "mode", "READ_ONLY");
    }

    @PostMapping(value = "${agentscope.agui.path-prefix:/agui}/run", produces = "text/event-stream")
    public SseEmitter run(@RequestBody RunAgentInput input,
            @RequestHeader(value = "${agentscope.agui.agent-id-header:X-Agent-Id}", required = false) String header,
            Authentication auth) {
        return execute(input, header, null, auth);
    }

    @PostMapping(value = "${agentscope.agui.path-prefix:/agui}/run/{agentId}", produces = "text/event-stream")
    public SseEmitter runWithAgent(@PathVariable String agentId, @RequestBody RunAgentInput input,
            @RequestHeader(value = "${agentscope.agui.agent-id-header:X-Agent-Id}", required = false) String header,
            Authentication auth) {
        return execute(input, header, agentId, auth);
    }

    private SseEmitter execute(RunAgentInput input, String header, String path, Authentication auth) {
        AgentActor actor = AgentIdentity.from(auth);
        validate(input);
        String requested = path != null ? path : header != null ? header :
                input.getForwardedProp("agentId") instanceof String id ? id : null;
        String mainId = factory.resolveMainId(actor, requested);
        String session = actor.userId() + ":" + mainId + ":" + input.getThreadId();
        if (activeSessions.putIfAbsent(session, true) != null) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "当前会话仍在处理上一轮请求");
        }
        try {
            Agent agent = factory.create(actor, mainId);
            var config = AguiAdapterConfig.builder().defaultAgentId(mainId)
                    .runTimeout(Duration.ofMinutes(3)).emitStateEvents(false).emitToolCallArgs(true).build();
            var processor = AguiRequestProcessor.builder().config(config).agentResolver(new AgentResolver() {
                public Agent resolveAgent(String id, String threadId) { return agent; }
                public boolean hasMemory(String threadId) { return false; }
            }).build();
            // 服务端使用用户命名空间；不接受客户端工具、状态或恢复指令。
            RunAgentInput safeInput = RunAgentInput.builder().threadId(session)
                    .runId(actor.userId() + ":" + input.getRunId()).messages(input.getMessages()).build();
            var runtime = RuntimeContext.builder().userId(Long.toString(actor.userId())).sessionId(session).build();
            var result = processor.process(safeInput, mainId, mainId, runtime);
            SseEmitter emitter = new SseEmitter(190_000L);
            AtomicReference<Disposable> subscription = new AtomicReference<>();
            AtomicBoolean closed = new AtomicBoolean();
            Runnable cleanup = () -> {
                if (closed.compareAndSet(false, true)) {
                    Disposable disposable = subscription.get();
                    if (disposable != null) disposable.dispose();
                    agent.interrupt();
                    activeSessions.remove(session);
                }
            };
            emitter.onCompletion(cleanup);
            emitter.onTimeout(() -> { cleanup.run(); emitter.complete(); });
            emitter.onError(e -> cleanup.run());
            Disposable disposable = result.events().subscribeOn(Schedulers.boundedElastic())
                    .doFinally(signal -> cleanup.run())
                    .subscribe(event -> {
                        try { emitter.send(SseEmitter.event().data(event)); }
                        catch (IOException | IllegalStateException e) { cleanup.run(); emitter.completeWithError(e); }
                    }, error -> {
                        try { emitter.send(SseEmitter.event().data(Map.of("type", "RUN_ERROR", "message", "智能助手执行失败，请稍后重试"))); }
                        catch (IOException | IllegalStateException ignored) { }
                        emitter.complete();
                    }, emitter::complete);
            subscription.set(disposable);
            if (closed.get()) disposable.dispose();
            return emitter;
        } catch (RuntimeException e) {
            activeSessions.remove(session);
            throw e;
        }
    }

    static void validate(RunAgentInput input) {
        if (input == null || input.getThreadId() == null || !input.getThreadId().matches("[A-Za-z0-9_-]{1,128}")
                || input.getRunId() == null || !input.getRunId().matches("[A-Za-z0-9_-]{1,128}")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "会话与运行编号格式不正确");
        }
        if (input.hasTools() || input.hasState() || input.hasContext() || input.hasResume()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "当前入口仅支持服务端只读工具，不接受客户端工具、状态或恢复指令");
        }
        if (!input.hasMessages() || input.getMessages().size() > 40) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "消息数必须在 1 到 40 之间");
        }
        for (var message : input.getMessages()) {
            if (message == null || !("user".equals(message.getRole()) || "assistant".equals(message.getRole()))
                    || message.hasBlocks() || message.hasToolCalls() || message.getToolCallId() != null
                    || message.getTextContent() == null || message.getTextContent().length() > 8000) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "仅允许用户和助手对话历史");
            }
        }
    }
}
