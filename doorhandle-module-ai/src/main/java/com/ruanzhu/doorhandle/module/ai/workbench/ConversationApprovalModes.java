package com.ruanzhu.doorhandle.module.ai.workbench;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.AgentApprovalMode;
import com.ruanzhu.doorhandle.contracts.agent.AgentChatSessionApi;
import com.ruanzhu.doorhandle.module.ai.agent.AgentRunRegistry;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.Objects;
import java.util.Set;

import static com.ruanzhu.doorhandle.module.ai.workbench.WorkbenchStore.fail;

@Service
@ConditionalOnExpression("${agentscope.ai.enabled:false} and ${agentscope.workbench.enabled:false}")
public class ConversationApprovalModes {
    public record Selection(AgentApprovalMode mode, long revision) {}

    private record Saved(AgentApprovalMode mode, long revision, String requestId) {}

    private final JdbcTemplate jdbc;
    private final WorkbenchStore workbench;
    private final ObjectProvider<AgentChatSessionApi> sessions;
    private final AgentRunRegistry runs;

    public ConversationApprovalModes(JdbcTemplate jdbc, WorkbenchStore workbench,
                                     ObjectProvider<AgentChatSessionApi> sessions, AgentRunRegistry runs) {
        this.jdbc = jdbc;
        this.workbench = workbench;
        this.sessions = sessions;
        this.runs = runs;
    }

    public Selection read(AgentActor actor, String session) {
        sessions.getObject().assertOwned(actor, session);
        var saved = saved(actor, session);
        return new Selection(saved.mode(), saved.revision());
    }

    public Selection select(AgentActor actor, String session, AgentApprovalMode mode, long revision, String requestId) {
        sessions.getObject().assertOwned(actor, session);
        if (mode == null || revision < 0 || requestId == null || !requestId.matches("[A-Za-z0-9_-]{1,128}")) {
            throw fail(400, "请核对审批模式参数与版本");
        }
        return workbench.locked(actor.userId(), () -> {
            var saved = saved(actor, session);
            if (requestId.equals(saved.requestId())) {
                if (saved.mode() != mode || saved.revision() != revision + 1) {
                    throw fail(409, "请求编号已使用，请重新核对审批模式");
                }
                return new Selection(saved.mode(), saved.revision());
            }
            if (saved.revision() != revision) throw fail(409, "审批模式已变化，请刷新核对");
            var job = WorkbenchStore.mainSlot(workbench, actor.userId(), session).current();
            if (runs.isActive(actor, session) || job != null && !Set.of("COMPLETED", "CANCELLED").contains(job.status())) {
                throw fail(409, "请先结束当前任务，再切换下一轮的审批模式");
            }
            if (saved.mode() == mode) return new Selection(mode, revision);
            jdbc.update("""
                INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,state_code,current_ref,created_at,updated_at)
                VALUES('AGENT_APPROVAL_MODE',?,?,?,?,?,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE revision=VALUES(revision),state_code=VALUES(state_code),
                    current_ref=VALUES(current_ref),updated_at=UTC_TIMESTAMP(6)
                """, actor.userId(), session, revision + 1, mode.name(), requestId);
            return new Selection(mode, revision + 1);
        });
    }

    private Saved saved(AgentActor actor, String session) {
        return jdbc.query("""
                SELECT state_code,revision,current_ref FROM runtime_state
                WHERE namespace='AGENT_APPROVAL_MODE' AND owner_id=? AND scope_key=?
                """, (row, index) -> new Saved(AgentApprovalMode.valueOf(Objects.requireNonNull(row.getString("state_code"))),
                        row.getLong("revision"), row.getString("current_ref")), actor.userId(), session)
                .stream().findFirst().orElseGet(() -> new Saved(AgentApprovalMode.DEFAULT, 0, null));
    }
}
