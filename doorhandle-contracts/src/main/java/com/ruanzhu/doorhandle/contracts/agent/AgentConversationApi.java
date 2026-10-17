package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;

/** Agent 模块的内部执行门面；身份与历史只能由服务端构造，不暴露 SDK 类型。 */
public interface AgentConversationApi {
    record Message(String role, String content) {}
    record Event(String type, String agent, String tool, String text, long elapsedMs) {}
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
    Status status();
    default int maxRunSeconds() { return 180; }
    default void checkRequest(AgentActor actor, String entryPoint, String requestId) {}
}
