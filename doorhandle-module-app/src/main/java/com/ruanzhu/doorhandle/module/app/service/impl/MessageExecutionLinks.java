package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import java.util.*;

/** 只关联服务端已保存的助手消息与同账号、同会话的真实运行，不推断旧历史。 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MessageExecutionLinks {
    private final JdbcTemplate jdbc;
    private volatile long retryAfter;

    public void bind(TenantContext tenant, String sessionId, Long messageId, String runId) {
        if (!valid(tenant, sessionId) || messageId == null || messageId <= 0
                || runId == null || !runId.matches("[A-Za-z0-9_:.-]{1,36}") || coolingDown()) return;
        try {
            jdbc.update("""
                INSERT INTO agent_message_execution(user_id,session_id,message_id,run_id)
                SELECT ?,m.session_id,m.id,r.run_id FROM chat_message m
                JOIN chat_session s ON s.session_id=m.session_id
                JOIN agent_run r ON r.user_id=s.user_id AND r.session_id=s.session_id
                WHERE s.user_id=? AND s.session_id=? AND m.id=? AND m.role='assistant'
                  AND m.message_type IN ('TEXT','AGENT_CARDS') AND r.run_id=?
                  AND r.entry_point IN ('CHAT','AGUI') AND r.status IN ('COMPLETED','INTERRUPTED')
                ON DUPLICATE KEY UPDATE message_id=agent_message_execution.message_id
                """, tenant.userId(), tenant.userId(), sessionId, messageId, runId);
        } catch (DataAccessException error) { unavailable(error); }
    }

    /** 每 200 条可见消息批量读取一次，避免逐条气泡查询数据库。 */
    public void hydrate(TenantContext tenant, String sessionId, List<ChatMessageResponse> messages) {
        if (!valid(tenant, sessionId) || messages == null || coolingDown()) return;
        var targets = messages.stream().filter(Objects::nonNull)
                .filter(message -> "assistant".equals(message.getRole()) && message.getId() != null)
                .filter(message -> Set.of("TEXT", "AGENT_CARDS").contains(Objects.toString(message.getMessageType(), "")))
                .filter(message -> sessionId.equals(message.getSessionId())).toList();
        if (targets.isEmpty()) return;
        Map<Long,String> links = new HashMap<>();
        try {
            for (int offset = 0; offset < targets.size(); offset += 200) {
                var batch = targets.subList(offset, Math.min(offset + 200, targets.size()));
                var args = new ArrayList<Object>(List.of(tenant.userId(), sessionId));
                batch.forEach(message -> args.add(message.getId()));
                var rows = jdbc.queryForList("""
                    SELECT l.message_id,l.run_id FROM agent_message_execution l
                    JOIN chat_message m ON m.id=l.message_id AND m.session_id=l.session_id
                    JOIN chat_session s ON s.session_id=l.session_id AND s.user_id=l.user_id
                    JOIN agent_run r ON r.run_id=l.run_id AND r.user_id=l.user_id AND r.session_id=l.session_id
                    WHERE l.user_id=? AND l.session_id=? AND m.role='assistant' AND l.message_id IN (
                    """ + String.join(",", Collections.nCopies(batch.size(), "?")) + ")", args.toArray());
                for (var row : rows) {
                    Object id = row.get("message_id"), run = row.get("run_id");
                    if (id instanceof Number number && run instanceof String value
                            && value.matches("[A-Za-z0-9_:.-]{1,36}")) links.put(number.longValue(), value);
                }
            }
            // 全批次成功才补充关联，查询失败不会让半页消息出现推断结果。
            targets.forEach(message -> message.setRunId(links.get(message.getId())));
        } catch (DataAccessException error) { unavailable(error); }
    }

    private boolean valid(TenantContext tenant, String session) {
        return tenant != null && session != null && !session.isBlank() && session.length() <= 128;
    }
    private boolean coolingDown() { return System.currentTimeMillis() < retryAfter; }
    private synchronized void unavailable(DataAccessException error) {
        if (!coolingDown()) log.warn("消息执行关联暂不可用，60 秒后重试；请核对 V66 迁移及数据库连接：errorType={}", error.getClass().getSimpleName());
        retryAfter = System.currentTimeMillis() + 60_000;
    }
}
