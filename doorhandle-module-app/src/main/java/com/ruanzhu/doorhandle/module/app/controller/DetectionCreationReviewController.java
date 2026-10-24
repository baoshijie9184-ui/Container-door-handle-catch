package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.app.service.impl.AgentWorkspaceService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

/** App owns HTTP/session access; detection owns all creation commands and reconciliation data. */
@RestController
@RequestMapping("/api/agent/conversations/{session}/detection-creations")
@ConditionalOnProperty(prefix="agentscope.workbench",name="enabled",havingValue="true")
public class DetectionCreationReviewController {
    private final AgentWorkspaceService workspace;private final ObjectProvider<DetectionCreationApi> creation;
    public DetectionCreationReviewController(AgentWorkspaceService workspace,ObjectProvider<DetectionCreationApi> creation){this.workspace=workspace;this.creation=creation;}
    @ModelAttribute void privacy(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    private AgentActor actor(Authentication auth,String session){
        if(auth==null||!auth.isAuthenticated()||!(auth.getPrincipal() instanceof TenantPrincipal user))throw fail(401,"请先登录");
        var roles=auth.getAuthorities().stream().map(value->value.getAuthority()).toList();var role=roles.contains("ROLE_SUPERVISOR")?AgentActor.Role.SUPERVISOR:roles.contains("ROLE_INSPECTOR")?AgentActor.Role.INSPECTOR:null;
        if(role==null)throw fail(403,"当前账号无工作台权限");var actor=new AgentActor(user.userId(),user.username(),role);workspace.assertOwned(actor,session);return actor;
    }
    private DetectionCreationApi service(){var api=creation.getIfAvailable();if(api==null)throw fail(503,"会话图片创建检测尚未启用");return api;}
    @GetMapping public Object list(Authentication auth,@PathVariable String session){var owner=actor(auth,session);return creation.getIfAvailable()==null?java.util.List.of():service().transferReviews(owner,session);}
    public record Command(@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,128}") String requestId,@Min(0) long revision,
                          @NotBlank @Pattern(regexp="CHECK|FINALIZE|ABANDON") String action,@Pattern(regexp="[a-f0-9-]{36}") String checkId){}
    @PostMapping("/{command}/review") public Object command(Authentication auth,@PathVariable String session,@PathVariable String command,
            @Valid @RequestBody Command body,HttpServletRequest request){
        if(!"workbench".equals(request.getHeader("X-Agent-Action"))||!body.requestId().equals(request.getHeader("X-Request-ID"))||"cross-site".equals(request.getHeader("Sec-Fetch-Site")))throw fail(403,"核对请求无效");
        return service().reviewTransfer(actor(auth,session),session,command,new DetectionCreationApi.ReviewCommand(body.requestId(),body.revision(),body.action(),body.checkId()));
    }
    @ExceptionHandler(ResponseStatusException.class) ResponseEntity<?> invalid(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).body(Map.of("message",error.getReason()==null?"请求无效":error.getReason()));}
    @ExceptionHandler(SecurityException.class) ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","当前账号无法执行此操作"));}
    @ExceptionHandler(IllegalArgumentException.class) ResponseEntity<?> bad(IllegalArgumentException error){return ResponseEntity.badRequest().body(Map.of("message",error.getMessage()==null?"核对参数无效":error.getMessage()));}
    @ExceptionHandler(IllegalStateException.class) ResponseEntity<?> conflict(IllegalStateException error){return ResponseEntity.status(409).body(Map.of("message",error.getMessage()==null?"核对状态已变化 请刷新":error.getMessage()));}
    @ExceptionHandler(org.springframework.dao.DataAccessException.class) ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","核对存储暂不可用 请刷新原请求结果 不会自动重做"));}
    private static ResponseStatusException fail(int status,String text){return new ResponseStatusException(HttpStatus.valueOf(status),text);}
}
