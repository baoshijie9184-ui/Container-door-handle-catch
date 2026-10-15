package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.function.Consumer;

/** 服务端持久会话门面。外部入口只能提交本轮问题，不能覆盖历史或记忆所属账号。 */
public interface AgentChatSessionApi {
    record Reply(String text, String runId, List<AgentCards.Reference> cards) {}
    record Run(CompletableFuture<Reply> result, Runnable cancel) {}

    Run start(AgentActor actor, String sessionId, String requestId, String question,
              Consumer<AgentConversationApi.Event> events);
}
