package com.ruanzhu.doorhandle.module.ai.research;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.time.LocalDateTime;

/** 账号固定时间窗；额度与文件审计使用同一事务，失败不消耗额度。 */
@Service
@ConditionalOnProperty(prefix="agentscope.research",name={"enabled","export-enabled","export-rate-limit-enabled"},havingValue="true")
public class ResearchExportRateLimit {
    public static final class Limited extends ResponseStatusException {
        private final long retryAfterSeconds;
        public Limited(long seconds) {
            super(HttpStatus.TOO_MANY_REQUESTS,"本账号导出过于频繁，请等待后重新确认；不会自动重试");
            retryAfterSeconds=Math.max(1,seconds);
        }
        @Override public HttpHeaders getHeaders() {
            var headers=new HttpHeaders();
            headers.set(HttpHeaders.RETRY_AFTER,Long.toString(retryAfterSeconds));
            return HttpHeaders.readOnlyHttpHeaders(headers);
        }
    }
    private final JdbcTemplate jdbc;
    private final int maxExports;
    private final int windowSeconds;
    public ResearchExportRateLimit(JdbcTemplate jdbc,ResearchEvidenceProperties properties) {
        this.jdbc=jdbc;maxExports=properties.getExportMaxPerWindow();windowSeconds=properties.getExportWindowSeconds();
    }
    @PostConstruct public void schema() {
        if(maxExports<1||maxExports>100||windowSeconds<1||windowSeconds>3600)
            throw new IllegalStateException("来源导出限流参数超出范围：次数 1—100，时间窗 1—3600 秒");
        try { jdbc.queryForList("SELECT user_id,window_ends_at,export_count FROM agent_research_export_limit WHERE 1=0"); }
        catch(org.springframework.dao.DataAccessException error) {
            throw new IllegalStateException("请先执行 migration-V35-agent-research-export-limit.sql 再启用导出限流");
        }
    }
    void consume(AgentActor actor) {
        if(!TransactionSynchronizationManager.isActualTransactionActive()||actor.userId()<1)
            throw new IllegalStateException("来源导出限流需要账号事务");
        jdbc.update("INSERT INTO agent_research_export_limit(user_id) VALUES(?) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id)",actor.userId());
        var row=jdbc.queryForObject("SELECT window_ends_at,export_count FROM agent_research_export_limit WHERE user_id=? FOR UPDATE",
                (rs,index)->new Window(rs.getObject(1,LocalDateTime.class),rs.getInt(2)),actor.userId());
        // 在账号行锁之后读取数据库时间，多个应用实例不依赖各自的系统时钟。
        var now=jdbc.queryForObject("SELECT CURRENT_TIMESTAMP(6)",LocalDateTime.class);
        if(!now.isBefore(row.endsAt())) {
            jdbc.update("UPDATE agent_research_export_limit SET window_ends_at=?,export_count=1 WHERE user_id=?",now.plusSeconds(windowSeconds),actor.userId());
        } else {
            if(row.count()>=maxExports) {
                long remaining=Duration.between(now,row.endsAt()).toNanos();
                throw new Limited((remaining+999999999L)/1000000000L);
            }
            jdbc.update("UPDATE agent_research_export_limit SET export_count=export_count+1 WHERE user_id=?",actor.userId());
        }
    }
    private record Window(LocalDateTime endsAt,int count) {}
}
