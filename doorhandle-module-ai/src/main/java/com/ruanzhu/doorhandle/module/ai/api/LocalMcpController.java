package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@RestController @RequestMapping("/api/agent/mcp/fetch")
@ConditionalOnProperty(prefix="agentscope.mcp",name="enabled",havingValue="true")
public class LocalMcpController {
    private final LocalMcpService service;
    public LocalMcpController(LocalMcpService service){this.service=service;}
    @ModelAttribute public void noCache(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    @GetMapping public Object view(Authentication auth){return service.view(AgentIdentity.from(auth));}
    @PostMapping("/install") public ResponseEntity<?> install(Authentication auth,@Valid @RequestBody Install command,@RequestHeader(value="X-MCP-Action",defaultValue="") String action){write(action);return ResponseEntity.accepted().body(service.install(AgentIdentity.from(auth),command.expectedRevision(),command.requestId(),command.licenseAccepted()));}
    @PostMapping("/enabled") public Object enabled(Authentication auth,@Valid @RequestBody Enable command,@RequestHeader(value="X-MCP-Action",defaultValue="") String action){write(action);return service.enabled(AgentIdentity.from(auth),command.expectedRevision(),command.enabled());}
    @PostMapping("/install/cancel") public Object cancelInstallation(Authentication auth,@Valid @RequestBody CancelInstall command,@RequestHeader(value="X-MCP-Action",defaultValue="") String action){write(action);return service.cancelInstallation(AgentIdentity.from(auth),command.expectedRevision(),command.operationId(),command.confirmed());}
    @PostMapping("/registration/remove") public Object removeRegistration(Authentication auth,@Valid @RequestBody RemoveRegistration command,@RequestHeader(value="X-MCP-Action",defaultValue="") String action){write(action);return service.removeRegistration(AgentIdentity.from(auth),command.expectedRevision(),command.operationId(),command.confirmed());}
    @PostMapping("/probe") public Object probe(Authentication auth,@RequestHeader(value="X-MCP-Action",defaultValue="") String action){write(action);return service.probe(AgentIdentity.from(auth));}
    public record Install(@Min(0) int expectedRevision,@NotBlank @Pattern(regexp="[A-Za-z0-9_-]{8,64}") String requestId,@AssertTrue boolean licenseAccepted){}
    public record Enable(@Min(0) int expectedRevision,@NotNull Boolean enabled){}
    public record CancelInstall(@NotNull @Min(0) Integer expectedRevision,@NotNull @Pattern(regexp="[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}") String operationId,@AssertTrue boolean confirmed){}
    public record RemoveRegistration(@NotNull @Min(0) Integer expectedRevision,@NotNull @Pattern(regexp="[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}") String operationId,@AssertTrue boolean confirmed){}
    private void write(String action){if(!"update".equals(action))throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"MCP 操作请求格式不正确");}
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> invalid(ResponseStatusException e){return ResponseEntity.status(e.getStatusCode()).body(Map.of("message",e.getReason()==null?"MCP 请求无效":e.getReason()));}
    @ExceptionHandler({org.springframework.web.bind.MethodArgumentNotValidException.class,org.springframework.http.converter.HttpMessageNotReadableException.class}) public ResponseEntity<?> invalid(){return ResponseEntity.badRequest().body(Map.of("message","请核对安装参数、版本和许可确认项"));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","当前身份不能访问 MCP"));}
    @ExceptionHandler(RuntimeException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","MCP 操作结果尚未核实 请刷新后核对"));}
}
