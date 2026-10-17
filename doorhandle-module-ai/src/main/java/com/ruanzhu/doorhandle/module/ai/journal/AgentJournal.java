package com.ruanzhu.doorhandle.module.ai.journal;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Consumer;

/** 应用运行日志边界，不保存 SDK 状态、消息正文或凭证。 */
public interface AgentJournal {
    record RunView(String runId, String sessionId, String entryPoint, String mainAgent, String status,
                   String defaultModel, String policyVersion, LocalDateTime startedAt, LocalDateTime endedAt, long lastSequence) {}
    record EventView(long sequence, String type, LocalDateTime occurredAt, Map<String, Object> payload) {}
    interface Run {
        String id();
        void event(String type, Map<String, Object> payload);
        void finish(String status);
        void bindCancel(Runnable cancel);
    }
    Run begin(AgentActor actor, String sessionId, String mainAgent, String entryPoint, String requestKey, String defaultModel);
    /** Internal professional execution; HTTP conversation entry points remain CHAT/AGUI only. */
    default Run beginChild(AgentActor actor,String sessionId,String specialist,String requestKey,String model){return begin(actor,sessionId,specialist,"CHILD",requestKey,model);}
    List<RunView> list(AgentActor actor, String sessionId, String beforeRunId, int limit);
    RunView get(AgentActor actor, String runId);
    List<EventView> events(AgentActor actor, String runId, long after, int limit);
    RunView cancel(AgentActor actor, String runId);
    boolean enabled();
    default void checkRequest(AgentActor actor, String entryPoint, String requestId) {}

    static AgentJournal disabled() {
        return new AgentJournal() {
            public boolean enabled() { return false; }
            public Run begin(AgentActor actor, String sessionId, String mainAgent, String entryPoint, String requestKey, String model) {
                String id = UUID.randomUUID().toString();
                return new Run() {
                    public String id() { return id; }
                    public void event(String type, Map<String, Object> payload) {}
                    public void finish(String status) {}
                    public void bindCancel(Runnable cancel) {}
                };
            }
            private UnsupportedOperationException unavailable() { return new UnsupportedOperationException("运行日志未启用"); }
            public List<RunView> list(AgentActor a, String s, String b, int l) { throw unavailable(); }
            public RunView get(AgentActor a, String r) { throw unavailable(); }
            public List<EventView> events(AgentActor a, String r, long c, int l) { throw unavailable(); }
            public RunView cancel(AgentActor a, String r) { throw unavailable(); }
        };
    }
}
