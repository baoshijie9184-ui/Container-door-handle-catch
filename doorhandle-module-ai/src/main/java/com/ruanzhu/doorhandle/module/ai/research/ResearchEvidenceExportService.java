package com.ruanzhu.doorhandle.module.ai.research;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** 只导出服务端重新授权读取的视图，审计提交成功后才向调用方交付文件。 */
@Service
@ConditionalOnProperty(prefix="agentscope.research",name={"enabled","export-enabled"},havingValue="true")
public class ResearchEvidenceExportService {
    public record Download(String exportId,String sha256,byte[] bytes) {}
    public record Document(int version,String exportId,Instant exportedAt,ResearchEvidenceDtos.View evidence,List<String> limitations) {}
    private final ResearchEvidenceService research;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper json;
    private final ResearchExportRateLimit rateLimit;
    public ResearchEvidenceExportService(ResearchEvidenceService research,JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json) {
        this(research,jdbc,manager,json,null);
    }
    @org.springframework.beans.factory.annotation.Autowired
    public ResearchEvidenceExportService(ResearchEvidenceService research,JdbcTemplate jdbc,PlatformTransactionManager manager,ObjectMapper json,
            @org.springframework.lang.Nullable ResearchExportRateLimit rateLimit) {
        this.research=research;this.jdbc=jdbc;this.json=json.copy().registerModule(new JavaTimeModule()).disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        this.rateLimit=rateLimit;
        tx=new TransactionTemplate(manager);tx.setTimeout(15);tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
    }
    @PostConstruct public void schema() {
        try { jdbc.queryForList("SELECT export_id FROM agent_research_export_audit WHERE 1=0"); }
        catch(org.springframework.dao.DataAccessException error) { throw new IllegalStateException("请先执行 migration-V33-agent-research-export.sql 再启用来源导出"); }
    }
    public Download export(AgentActor actor,String runId,boolean confirmed) {
        if(!confirmed)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"请先确认将本人来源摘录保存到本机");
        return tx.execute(status->{
            var view=research.view(actor,runId); // 包含本人运行授权及数据库时间的过期过滤，不接受客户端来源正文。
            if(rateLimit!=null) {
                rateLimit.consume(actor);
                view=research.view(actor,runId); // 行锁等待后再次授权与过滤，避免交付等待期间到期的内容。
            }
            String id=UUID.randomUUID().toString();
            byte[] bytes;
            try { bytes=json.writeValueAsBytes(new Document(1,id,Instant.now(),view,List.of(
                    "仅包含本次读取时仍可查看的脱敏来源片段；过期内容不包含在文件中",
                    "来源和摘录是未受信任文本；引用标记不证明结论已核实",
                    "不含完整网页快照、最终重定向地址或聊天正文；下载后请自行保管"))); }
            catch(JsonProcessingException error) { throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"来源文件暂时无法生成"); }
            if(bytes.length>524288)throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,"来源文件超过导出上限");
            String hash=ResearchEvidenceService.sha256(new String(bytes,StandardCharsets.UTF_8));
            jdbc.update("""
                INSERT INTO agent_research_export_audit(export_id,user_id,run_id,format_version,source_count,expired_source_count,payload_bytes,payload_sha256)
                VALUES(?,?,?,?,?,?,?,?)
                """,id,actor.userId(),runId,1,view.sources().size(),view.expiredSourceCount(),bytes.length,hash);
            return new Download(id,hash,bytes);
        });
    }
}
