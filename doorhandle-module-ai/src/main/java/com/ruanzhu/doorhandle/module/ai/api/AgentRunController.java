package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/agent/runs")
@Tag(name="Agent 运行记录",description="当前账号的持久运行与脱敏事件，只读补读不重新执行模型")
public class AgentRunController {
    private final AgentJournal journal;
    public AgentRunController(AgentJournal journal) { this.journal=journal; }
    @GetMapping public List<AgentJournal.RunView> list(Authentication auth,@RequestParam(required=false) String sessionId,
            @RequestParam(required=false) String beforeRunId,@RequestParam(defaultValue="20") int limit) {
        return journal.list(AgentIdentity.from(auth),sessionId,beforeRunId,limit);
    }
    @GetMapping("/{runId}") public AgentJournal.RunView get(Authentication auth,@PathVariable String runId) { return journal.get(AgentIdentity.from(auth),runId); }
    @GetMapping("/{runId}/events") public List<AgentJournal.EventView> events(Authentication auth,@PathVariable String runId,
            @RequestParam(defaultValue="0") long after,@RequestParam(defaultValue="100") int limit) {
        return journal.events(AgentIdentity.from(auth),runId,after,limit);
    }
    @PostMapping("/{runId}/cancel") public AgentJournal.RunView cancel(Authentication auth,@PathVariable String runId,
            @RequestHeader(value="X-Agent-Action",defaultValue="") String action) {
        if (!"cancel".equals(action)) throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST,"取消请求格式不正确");
        return journal.cancel(AgentIdentity.from(auth),runId);
    }
    @ExceptionHandler(org.springframework.web.server.ResponseStatusException.class)
    public org.springframework.http.ResponseEntity<?> invalid(org.springframework.web.server.ResponseStatusException error) {
        return org.springframework.http.ResponseEntity.status(error.getStatusCode()).body(java.util.Map.of("message",error.getReason()==null?"请求无效":error.getReason()));
    }
    @ExceptionHandler(org.springframework.dao.DataAccessException.class)
    public org.springframework.http.ResponseEntity<?> storageUnavailable() {
        return org.springframework.http.ResponseEntity.status(503).body(java.util.Map.of("message","运行记录存储暂不可用，请稍后重试"));
    }
    @ExceptionHandler(org.springframework.security.access.AccessDeniedException.class)
    public org.springframework.http.ResponseEntity<?> forbidden() {
        return org.springframework.http.ResponseEntity.status(403).body(java.util.Map.of("message","当前身份没有运行记录访问权限"));
    }
}
