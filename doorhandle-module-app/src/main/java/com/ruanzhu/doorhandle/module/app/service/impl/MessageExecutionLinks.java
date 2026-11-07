package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.module.app.dto.chat.ChatMessageResponse;
import com.ruanzhu.doorhandle.module.system.security.TenantContext;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.persistence.chat.JdbcMessageEvidenceStore;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import java.util.*;

/** 只关联服务端已保存的助手消息与同账号、同会话的真实运行，不推断旧历史。 */
@Slf4j
@Service
public class MessageExecutionLinks {
    private final JdbcTemplate jdbc;
    private final JdbcMessageEvidenceStore evidence;
    private final org.springframework.transaction.support.TransactionTemplate tx;
    private volatile long retryAfter;
    public MessageExecutionLinks(JdbcTemplate jdbc){
        this.jdbc=jdbc;evidence=new JdbcMessageEvidenceStore(jdbc,new ObjectMapper());
        tx=new org.springframework.transaction.support.TransactionTemplate(new org.springframework.jdbc.datasource.DataSourceTransactionManager(Objects.requireNonNull(jdbc.getDataSource())));
    }

    public void bind(TenantContext tenant, String sessionId, Long messageId, String runId) {
        if (!valid(tenant, sessionId) || messageId == null || messageId <= 0
                || runId == null || !runId.matches("[A-Za-z0-9_:.-]{1,36}") || coolingDown()) return;
        try {
            tx.executeWithoutResult(status->evidence.bindExecution(tenant.userId(),sessionId,messageId,runId));
        } catch (DuplicateKeyException alreadyLinked) {
            // The unique run binding is immutable, including races between two replies.
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
        Map<Long,com.ruanzhu.doorhandle.framework.persistence.chat.MessageEvidence.ExecutionLink> links = new HashMap<>();
        try {
            for (int offset = 0; offset < targets.size(); offset += 200) {
                var batch = targets.subList(offset, Math.min(offset + 200, targets.size()));
                links.putAll(evidence.executionDetails(tenant.userId(),sessionId,batch.stream().map(ChatMessageResponse::getId).toList()));
            }
            // 全批次成功才补充关联，查询失败不会让半页消息出现推断结果。
            targets.forEach(message -> {var link=links.get(message.getId());message.setRunId(link==null?null:link.runId());message.setExecutionClockStatus(link==null?null:link.clockStatus());message.setExecutionSourceWallTimes(link==null?null:link.sourceWallTimes());});
        } catch (DataAccessException error) { unavailable(error); }
    }

    private boolean valid(TenantContext tenant, String session) {
        return tenant != null && session != null && !session.isBlank() && session.length() <= 128;
    }
    private boolean coolingDown() { return System.currentTimeMillis() < retryAfter; }
    private synchronized void unavailable(DataAccessException error) {
        if (!coolingDown()) log.warn("消息执行关联暂不可用，60 秒后重试；请核对独立消息证据迁移及数据库连接：errorType={}", error.getClass().getSimpleName());
        retryAfter = System.currentTimeMillis() + 60_000;
    }
}
