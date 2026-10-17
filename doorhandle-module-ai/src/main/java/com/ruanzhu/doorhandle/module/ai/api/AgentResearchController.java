package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import com.ruanzhu.doorhandle.module.ai.research.*;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.ResponseEntity;
import org.springframework.lang.Nullable;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@RestController
@RequestMapping("/api/agent/runs")
@Tag(name = "Agent 调研来源", description = "按账号和运行隔离的来源摘录与引用标记")
public class AgentResearchController {
    private final AgentJournal journal;
    private final ResearchEvidenceService research;
    private final ResearchEvidenceExportService exports;
    public AgentResearchController(AgentJournal journal, @Nullable ResearchEvidenceService research) { this(journal,research,null); }
    @org.springframework.beans.factory.annotation.Autowired
    public AgentResearchController(AgentJournal journal, @Nullable ResearchEvidenceService research,@Nullable ResearchEvidenceExportService exports) { this.journal=journal;this.research=research;this.exports=exports; }
    @GetMapping("/{runId}/sources")
    @Operation(summary = "读取本人运行的已登记来源，不重新抓取网页")
    public ResponseEntity<ResearchEvidenceDtos.View> sources(Authentication auth, @PathVariable String runId) {
        var actor=AgentIdentity.from(auth);
        journal.get(actor,runId);
        return ResponseEntity.ok().header("Cache-Control","no-store")
                .body((research==null?ResearchEvidenceDtos.View.disabled(runId):research.view(actor,runId)).withExportEnabled(exports!=null));
    }
    @PostMapping("/{runId}/sources/export")
    @Operation(summary="确认导出本人当前可查看的来源，提交摘要审计后返回 JSON 文件")
    public ResponseEntity<byte[]> export(Authentication auth,@PathVariable String runId,@RequestBody Map<String,Object> input,
            @RequestHeader(value="X-Agent-Action",defaultValue="") String action,
            @RequestHeader(value="Sec-Fetch-Site",defaultValue="") String fetchSite) {
        var actor=AgentIdentity.from(auth);journal.get(actor,runId);
        if(!"export".equals(action)||"cross-site".equals(fetchSite))throw new ResponseStatusException(org.springframework.http.HttpStatus.FORBIDDEN,"来源导出请求无效");
        if(exports==null)throw new ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"此环境尚未启用来源导出");
        if(input.size()!=1||!Boolean.TRUE.equals(input.get("confirmed")))throw new ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST,"请先确认将本人来源摘录保存到本机");
        var file=exports.export(actor,runId,true);
        return ResponseEntity.ok().header("Cache-Control","no-store").header("X-Content-Type-Options","nosniff")
                .header("Content-Disposition","attachment; filename=\"research-"+file.exportId()+".json\"")
                .header("X-Content-SHA256",file.sha256()).header("X-Export-Id",file.exportId())
                .contentType(org.springframework.http.MediaType.APPLICATION_JSON).body(file.bytes());
    }
    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<?> invalid(ResponseStatusException error) {
        return ResponseEntity.status(error.getStatusCode()).headers(error.getHeaders()).header("Cache-Control","no-store").body(Map.of("message",error.getReason()==null?"请求无效":error.getReason()));
    }
    @ExceptionHandler(org.springframework.dao.DataAccessException.class)
    public ResponseEntity<?> unavailable() { return ResponseEntity.status(503).header("Cache-Control","no-store").body(Map.of("message","调研来源存储暂不可用，请稍后重试")); }
}
