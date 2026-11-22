package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.contracts.agent.AgentApprovalMode;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.workbench.ConversationApprovalModes;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.lang.Nullable;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

@RestController
@RequestMapping("/api/agent/conversations/{sessionId}/approval-mode")
public class ConversationApprovalModeController {
    private final ConversationApprovalModes modes;

    public ConversationApprovalModeController(@Nullable ConversationApprovalModes modes) {
        this.modes = modes;
    }

    public record Change(@NotNull AgentApprovalMode mode, @NotNull @Min(0) Long revision,
                         @NotNull @Pattern(regexp = "[A-Za-z0-9_-]{1,128}") String requestId) {}

    @ModelAttribute
    void privateResponse(HttpServletResponse response) { response.setHeader("Cache-Control", "no-store"); }

    @GetMapping
    public ConversationApprovalModes.Selection read(Authentication auth, @PathVariable String sessionId) {
        var actor = AgentIdentity.from(auth);
        return service().read(actor, sessionId);
    }

    @PostMapping
    public ConversationApprovalModes.Selection select(Authentication auth, @PathVariable String sessionId,
                                                      @Valid @RequestBody Change change, HttpServletRequest request) {
        var actor = AgentIdentity.from(auth);
        if (!"workbench".equals(request.getHeader("X-Agent-Action")) || "cross-site".equals(request.getHeader("Sec-Fetch-Site"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "操作来源无效");
        }
        return service().select(actor, sessionId, change.mode(), change.revision(), change.requestId());
    }

    private ConversationApprovalModes service() {
        if (modes == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "当前环境未启用审批模式");
        return modes;
    }

    @ExceptionHandler(ResponseStatusException.class)
    ResponseEntity<?> invalid(ResponseStatusException error) {
        return ResponseEntity.status(error.getStatusCode()).body(Map.of("message", error.getReason() == null ? "审批模式请求无效" : error.getReason()));
    }

    @ExceptionHandler({SecurityException.class, org.springframework.security.access.AccessDeniedException.class})
    ResponseEntity<?> denied() {
        return ResponseEntity.status(403).body(Map.of("message", "当前身份不能访问此会话的审批模式"));
    }

    @ExceptionHandler({org.springframework.web.bind.MethodArgumentNotValidException.class,
            org.springframework.http.converter.HttpMessageNotReadableException.class})
    ResponseEntity<?> malformed() {
        return ResponseEntity.badRequest().body(Map.of("message", "请核对审批模式参数与版本"));
    }

    @ExceptionHandler(org.springframework.dao.DataAccessException.class)
    ResponseEntity<?> unavailable() {
        return ResponseEntity.status(503).body(Map.of("message", "审批模式暂不可核对，请重新读取"));
    }
}
