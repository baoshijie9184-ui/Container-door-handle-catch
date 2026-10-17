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
}
