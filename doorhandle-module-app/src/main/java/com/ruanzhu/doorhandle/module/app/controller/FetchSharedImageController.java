package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.AgentMcpImagesApi;
import com.ruanzhu.doorhandle.contracts.security.BusinessPrincipal;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@RestController
@RequestMapping("/api/agent/mcp/fetch/shared-images")
@ConditionalOnProperty(prefix="agentscope.mcp",name={"enabled","shared-image-cleanup-enabled"},havingValue="true")
public class FetchSharedImageController {
    private final AgentMcpImagesApi service;
    public FetchSharedImageController(AgentMcpImagesApi service){this.service=service;}
    private static AgentActor actor(Authentication auth){
        if(auth==null||!auth.isAuthenticated()||!(auth.getPrincipal() instanceof BusinessPrincipal principal)||principal.userId()==null||principal.userId()<1)throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,"请先登录");
        if(auth.getAuthorities().stream().noneMatch(value->"ROLE_SUPERVISOR".equals(value.getAuthority())))throw new ResponseStatusException(HttpStatus.FORBIDDEN,"仅主管可以管理共享镜像");
        return new AgentActor(principal.userId(),principal.username(),AgentActor.Role.SUPERVISOR);
    }
    @ModelAttribute public void privateResponse(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    @GetMapping public Object view(Authentication auth){return service.view(actor(auth));}
    @PostMapping("/cleanup") public Object cleanup(Authentication auth,@Valid @RequestBody Command command,@RequestHeader(value="X-MCP-Action",defaultValue="") String action){write(action);return service.cleanup(actor(auth),command.image(),command.expectedRevision(),command.requestId(),command.confirmed());}
    @PostMapping("/reconcile") public Object reconcile(Authentication auth,@Valid @RequestBody Command command,@RequestHeader(value="X-MCP-Action",defaultValue="") String action){write(action);return service.reconcile(actor(auth),command.image(),command.expectedRevision(),command.requestId(),command.confirmed());}
    public record Command(@NotNull @Pattern(regexp="sha256:[a-f0-9]{64}") String image,@NotNull @Min(0) Integer expectedRevision,@NotNull @Pattern(regexp="[a-f0-9-]{36}") String requestId,@AssertTrue boolean confirmed){}
    private static void write(String action){if(!"update".equals(action))throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"镜像操作请求格式不正确");}
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> invalid(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).body(Map.of("message",error.getReason()==null?"镜像请求无效":error.getReason()));}
    @ExceptionHandler({org.springframework.web.bind.MethodArgumentNotValidException.class,org.springframework.http.converter.HttpMessageNotReadableException.class}) public ResponseEntity<?> invalid(){return ResponseEntity.badRequest().body(Map.of("message","请核对镜像摘要、版本和确认项"));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","当前账号不能管理共享镜像"));}
    @ExceptionHandler(RuntimeException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","共享镜像操作结果需要刷新核对 不会自动重复删除"));}
}
