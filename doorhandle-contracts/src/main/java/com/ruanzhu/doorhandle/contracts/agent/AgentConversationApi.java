package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;

/** Agent 模块的内部执行门面；身份与历史只能由服务端构造，不暴露 SDK 类型。 */
public interface AgentConversationApi {
    /** A generated execution claim has no matching receipt; callers must not save it as success. */
    final class UnverifiedAnswerException extends IllegalStateException {
        public UnverifiedAnswerException() {
            super("本轮没有取得专业查询已启动的执行回执，回答未作为成功结果保存。请查看执行追溯，系统没有自动重试。");
        }
    }
    record Message(String role, String content) {}
    record ReferenceContext(String text, List<AgentContextDataApi.Source> sources) {
        public ReferenceContext {
            text = java.util.Objects.toString(text, "");
            sources = List.copyOf(sources);
            if (text.isBlank() && !sources.isEmpty()) {
                throw new IllegalArgumentException("空参考资料不能包含来源");
            }
        }
    }
    record Event(String type, String agent, String tool, String text, long elapsedMs, String callId, java.util.Map<String,Object> modelReceipt) {
        public Event(String type,String agent,String tool,String text,long elapsedMs,String callId){this(type,agent,tool,text,elapsedMs,callId,null);}
        public Event(String type,String agent,String tool,String text,long elapsedMs){this(type,agent,tool,text,elapsedMs,null);}
    }
    record Run(CompletableFuture<String> result, Runnable cancel, String runId, java.util.function.Supplier<List<AgentCards.Reference>> cards) {
        public Run(CompletableFuture<String> result, Runnable cancel, String runId) { this(result, cancel, runId, List::of); }
        public Run(CompletableFuture<String> result, Runnable cancel) { this(result, cancel, null); }
    }
    record Status(String framework, String mode, String defaultModel, boolean runJournalEnabled,boolean reportsEnabled,boolean reportDraftsEnabled) {
        public Status(String framework,String mode,String defaultModel,boolean runJournalEnabled){this(framework,mode,defaultModel,runJournalEnabled,false,false);}
        public Status(String framework, String mode, String defaultModel) { this(framework, mode, defaultModel, false); }
    }

    Run start(AgentActor actor, String sessionId, List<Message> messages, String referenceContext, Consumer<Event> events);
    default Run start(AgentActor actor, String sessionId, List<Message> messages, String referenceContext,
                      Consumer<Event> events, String entryPoint, String requestId) {
        return start(actor, sessionId, messages, referenceContext, events);
    }
    /** Scoped retrieval must be handled only by an implementation that preserves its source evidence. */
    default Run startWithReferences(AgentActor actor, String sessionId, List<Message> messages,
                                    ReferenceContext reference, Consumer<Event> events, String entryPoint, String requestId) {
        if (!reference.sources().isEmpty()) throw new IllegalStateException("当前 Agent 不支持受控参考资料");
        return start(actor, sessionId, messages, reference.text(), events, entryPoint, requestId);
    }
    Status status();
    default int maxRunSeconds() { return 180; }
    default void checkRequest(AgentActor actor, String entryPoint, String requestId) {}
    default boolean requestsCredentialRead(String content) { return false; }
}
