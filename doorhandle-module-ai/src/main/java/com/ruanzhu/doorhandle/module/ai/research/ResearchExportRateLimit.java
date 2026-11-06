package com.ruanzhu.doorhandle.module.ai.research;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.framework.persistence.JdbcTransactions;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
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
        try { jdbc.queryForList("SELECT owner_id,window_ends_at,counter_value FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT' AND 1=0"); }
        catch(org.springframework.dao.DataAccessException error) {
            throw new IllegalStateException("请先安装 compact 研究导出限流状态约束",error);
        }
    }
    void consume(AgentActor actor) {
        JdbcTransactions.requireActive(jdbc);
        if(actor.userId()<1)
            throw new IllegalStateException("来源导出限流需要账号事务");
        jdbc.update("INSERT INTO runtime_state(namespace,owner_id,scope_key,revision,window_ends_at,counter_value,created_at,updated_at) VALUES('RESEARCH_EXPORT_LIMIT',?,'',0,UTC_TIMESTAMP(6),0,NULL,NULL) ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id)",actor.userId());
        var row=jdbc.queryForObject("SELECT window_ends_at,counter_value FROM runtime_state WHERE namespace='RESEARCH_EXPORT_LIMIT' AND owner_id=? AND scope_key='' FOR UPDATE",
                (rs,index)->new Window(rs.getObject(1,LocalDateTime.class),rs.getLong(2)),actor.userId());
        // 在账号行锁之后读取数据库时间，多个应用实例不依赖各自的系统时钟。
        var now=jdbc.queryForObject("SELECT UTC_TIMESTAMP(6)",LocalDateTime.class);
        if(!now.isBefore(row.endsAt())) {
            jdbc.update("UPDATE runtime_state SET window_ends_at=?,counter_value=1 WHERE namespace='RESEARCH_EXPORT_LIMIT' AND owner_id=? AND scope_key=''",now.plusSeconds(windowSeconds),actor.userId());
        } else {
            if(row.count()>=maxExports) {
                long remaining=Duration.between(now,row.endsAt()).toNanos();
                throw new Limited((remaining+999999999L)/1000000000L);
            }
            jdbc.update("UPDATE runtime_state SET counter_value=counter_value+1 WHERE namespace='RESEARCH_EXPORT_LIMIT' AND owner_id=? AND scope_key=''",actor.userId());
        }
    }
    private record Window(LocalDateTime endsAt,long count) {}
}
