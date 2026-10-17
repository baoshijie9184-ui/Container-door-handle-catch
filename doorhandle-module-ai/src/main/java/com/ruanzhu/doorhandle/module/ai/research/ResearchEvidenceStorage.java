package com.ruanzhu.doorhandle.module.ai.research;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ColumnMapRowMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.util.concurrent.*;

/** 按账号跨运行串行校验额度；到期后仅清空展示内容，保留来源身份与引用依据。 */
@Service
@EnableConfigurationProperties(ResearchEvidenceProperties.class)
@ConditionalOnProperty(prefix="agentscope.research",name={"enabled","governance-enabled"},havingValue="true")
public class ResearchEvidenceStorage implements AutoCloseable {
    public static final class QuotaExceeded extends ResponseStatusException {
        public QuotaExceeded() { super(HttpStatus.TOO_MANY_REQUESTS,"本账号调研来源额度已满 请等待来源过期后重试"); }
    }
    private final JdbcTemplate jdbc;
    private final ResearchEvidenceProperties properties;
    private final TransactionTemplate cleanupTx;
    private final ScheduledExecutorService maintenance=Executors.newSingleThreadScheduledExecutor(r->{
        var thread=new Thread(r,"research-content-maintenance");thread.setDaemon(true);return thread;
    });
    public ResearchEvidenceStorage(JdbcTemplate jdbc,PlatformTransactionManager manager,ResearchEvidenceProperties properties) {
        this.jdbc=jdbc;this.properties=properties;cleanupTx=new TransactionTemplate(manager);
        cleanupTx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        cleanupTx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);cleanupTx.setTimeout(5);
    }
    @PostConstruct public void schema() {
        if(properties.getMaxSourcesPerUser()<1||properties.getMaxSourcesPerUser()>10000
                ||properties.getCleanupBatchSize()<1||properties.getCleanupBatchSize()>500
                ||properties.getCleanupDelayMs()<1000||properties.getCleanupDelayMs()>3600000)
            throw new IllegalStateException("调研来源存储治理参数超出范围");
        try {
            jdbc.queryForList("SELECT user_id FROM agent_research_storage_owner WHERE 1=0");
            jdbc.queryForList("SELECT source_id FROM agent_research_content_purge WHERE 1=0");
        } catch(org.springframework.dao.DataAccessException error) {
            throw new IllegalStateException("请先执行 migration-V32-agent-research-storage.sql 再启用存储治理");
        }
        if(properties.isPurgeEnabled())maintenance.scheduleWithFixedDelay(this::maintain,
                properties.getCleanupDelayMs(),properties.getCleanupDelayMs(),TimeUnit.MILLISECONDS);
    }
    void lockOwner(AgentActor actor) { lockOwner(actor.userId()); }
    private void lockOwner(long userId) {
        if(!TransactionSynchronizationManager.isActualTransactionActive()||userId<1)throw new IllegalStateException("来源存储治理需要账号事务");
        jdbc.update("INSERT INTO agent_research_storage_owner(user_id) VALUES(?) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id)",userId);
        jdbc.queryForObject("SELECT user_id FROM agent_research_storage_owner WHERE user_id=? FOR UPDATE",Long.class,userId);
    }
    void checkCapacity(AgentActor actor) {
        if(!TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("来源额度检查需要事务");
        Long active=jdbc.queryForObject("SELECT COUNT(*) FROM agent_research_source WHERE user_id=? AND expires_at>CURRENT_TIMESTAMP",Long.class,actor.userId());
        if(active!=null&&active>=properties.getMaxSourcesPerUser())throw new QuotaExceeded();
    }
    /** 内部维护入口，不作为 Agent 工具或 HTTP 接口暴露。 */
    public int purgeExpiredBatch() {
        if(!properties.isPurgeEnabled())return 0;
        var candidates=jdbc.query("""
            SELECT s.source_id,s.user_id FROM agent_research_source s
            WHERE s.expires_at<=CURRENT_TIMESTAMP AND NOT EXISTS
              (SELECT 1 FROM agent_research_content_purge p WHERE p.source_id=s.source_id)
            ORDER BY s.expires_at,s.id LIMIT ?
            """, statement->{statement.setInt(1,properties.getCleanupBatchSize());statement.setQueryTimeout(5);},new ColumnMapRowMapper());
        int cleared=0;long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
        for(var candidate:candidates) {
            if(System.nanoTime()>deadline)break;
            Integer changed=cleanupTx.execute(status->{
                long owner=((Number)candidate.get("user_id")).longValue();String sourceId=candidate.get("source_id").toString();
                lockOwner(owner);
                var rows=jdbc.queryForList("""
                    SELECT requested_url,title,excerpt FROM agent_research_source
                    WHERE user_id=? AND source_id=? AND expires_at<=CURRENT_TIMESTAMP FOR UPDATE
                    """,owner,sourceId);
                if(rows.isEmpty()||!jdbc.queryForList("SELECT source_id FROM agent_research_content_purge WHERE source_id=?",sourceId).isEmpty())return 0;
                var row=rows.get(0);int chars=row.get("requested_url").toString().length()+row.get("title").toString().length()+row.get("excerpt").toString().length();
                int updated=jdbc.update("UPDATE agent_research_source SET requested_url='',title='',excerpt='' WHERE user_id=? AND source_id=? AND expires_at<=CURRENT_TIMESTAMP",owner,sourceId);
                if(updated!=1)throw new IllegalStateException("到期来源内容未完成清理");
                jdbc.update("INSERT INTO agent_research_content_purge(source_id,user_id,cleared_chars) VALUES(?,?,?)",sourceId,owner,chars);
                return 1;
            });
            cleared+=changed==null?0:changed;
        }
        return cleared;
    }
    private void maintain() {
        try { purgeExpiredBatch(); }
        catch(RuntimeException error) { LoggerFactory.getLogger(getClass()).warn("调研来源到期内容清理未完成 将在下次维护时重试"); }
    }
    @Override @PreDestroy public void close() { maintenance.shutdownNow(); }
}
