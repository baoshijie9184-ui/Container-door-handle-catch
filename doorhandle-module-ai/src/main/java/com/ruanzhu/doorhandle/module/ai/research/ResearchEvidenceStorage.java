package com.ruanzhu.doorhandle.module.ai.research;

import com.ruanzhu.doorhandle.framework.persistence.JdbcOwnerLock;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
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
    private final ResearchSourceRepository sources;
    private final ScheduledExecutorService maintenance=Executors.newSingleThreadScheduledExecutor(r->{
        var thread=new Thread(r,"research-content-maintenance");thread.setDaemon(true);return thread;
    });
    public ResearchEvidenceStorage(JdbcTemplate jdbc,PlatformTransactionManager manager,ResearchEvidenceProperties properties) {
        this.jdbc=jdbc;this.properties=properties;cleanupTx=new TransactionTemplate(manager);
        this.sources=new ResearchSourceRepository(jdbc);
        cleanupTx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        cleanupTx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);cleanupTx.setTimeout(5);
    }
    @PostConstruct public void schema() {
        if(properties.getMaxSourcesPerUser()<1||properties.getMaxSourcesPerUser()>10000
                ||properties.getCleanupBatchSize()<1||properties.getCleanupBatchSize()>500
                ||properties.getCleanupDelayMs()<1000||properties.getCleanupDelayMs()>3600000)
            throw new IllegalStateException("调研来源存储治理参数超出范围");
        try {
            JdbcOwnerLock.validateSchema(jdbc);
            sources.validateSchema();
        } catch(org.springframework.dao.DataAccessException error) {
            throw new IllegalStateException("请先完成 compact schema 迁移再启用存储治理", error);
        }
        if(properties.isPurgeEnabled())maintenance.scheduleWithFixedDelay(this::maintain,
                properties.getCleanupDelayMs(),properties.getCleanupDelayMs(),TimeUnit.MILLISECONDS);
    }
    void lockOwner(AgentActor actor) { lockOwner(actor.userId()); }
    private void lockOwner(long userId) {
        if(!TransactionSynchronizationManager.isActualTransactionActive()||userId<1)throw new IllegalStateException("来源存储治理需要账号事务");
        JdbcOwnerLock.lock(jdbc, JdbcOwnerLock.Scope.RESEARCH_STORAGE, userId);
    }
    void checkCapacity(AgentActor actor) {
        if(!TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("来源额度检查需要事务");
        if(sources.countActive(actor.userId())>=properties.getMaxSourcesPerUser())throw new QuotaExceeded();
    }
    /** 内部维护入口，不作为 Agent 工具或 HTTP 接口暴露。 */
    public int purgeExpiredBatch() {
        if(!properties.isPurgeEnabled())return 0;
        var candidates=sources.purgeCandidates(properties.getCleanupBatchSize());
        int cleared=0;long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
        for(var candidate:candidates) {
            if(System.nanoTime()>deadline)break;
            Integer changed=cleanupTx.execute(status->{
                long owner=((Number)candidate.get("user_id")).longValue();String sourceId=candidate.get("source_id").toString();
                lockOwner(owner);
                return sources.purge(owner,sourceId);
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
