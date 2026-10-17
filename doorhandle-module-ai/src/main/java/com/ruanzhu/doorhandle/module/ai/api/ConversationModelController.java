package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.stream.Collectors;
import java.util.Map;

/** Session-owned model preference. A logical execution snapshots it before the first request. */
@RestController
@RequestMapping("/api/agent/conversations/{sessionId}/model-selection")
@ConditionalOnProperty(prefix="agentscope.workbench",name="enabled",havingValue="true")
public class ConversationModelController {
    private final AgentWorkbenchService workbench;
    private final AgentModelService models;
    public ConversationModelController(AgentWorkbenchService workbench,AgentModelService models){this.workbench=workbench;this.models=models;}
    public record Select(@NotNull @Size(max=160) String modelId,@Min(0) long revision,@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,128}") String requestId){}
    @GetMapping public ResponseEntity<AgentWorkbenchService.ModelSelection> get(Authentication auth,@PathVariable String sessionId){return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(workbench.modelSelection(AgentIdentity.from(auth),sessionId));}
    @PostMapping public ResponseEntity<AgentWorkbenchService.ModelSelection> select(Authentication auth,@PathVariable String sessionId,@Valid @RequestBody Select input,HttpServletRequest request){
        if(!"workbench".equals(request.getHeader("X-Agent-Action"))||"cross-site".equals(request.getHeader("Sec-Fetch-Site")))throw new ResponseStatusException(HttpStatus.FORBIDDEN,"操作来源无效");
        var configured=models.entries().stream().filter(AgentModelService.ModelInfo::configured).map(AgentModelService.ModelInfo::id).collect(Collectors.toSet());
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(workbench.selectModel(AgentIdentity.from(auth),sessionId,input.modelId(),input.revision(),input.requestId(),configured));
    }
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> invalid(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).cacheControl(CacheControl.noStore()).body(Map.of("message",error.getReason()==null?"模型选择请求无效":error.getReason()));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) public ResponseEntity<?> denied(){return ResponseEntity.status(403).cacheControl(CacheControl.noStore()).body(Map.of("message","当前身份不能访问此会话的模型选择"));}
    @ExceptionHandler({org.springframework.web.bind.MethodArgumentNotValidException.class,org.springframework.http.converter.HttpMessageNotReadableException.class}) public ResponseEntity<?> malformed(){return ResponseEntity.badRequest().cacheControl(CacheControl.noStore()).body(Map.of("message","请核对模型选择参数与版本"));}
    @ExceptionHandler(org.springframework.dao.DataAccessException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).cacheControl(CacheControl.noStore()).body(Map.of("message","模型选择结果暂不可核对，请刷新后确认"));}
}
