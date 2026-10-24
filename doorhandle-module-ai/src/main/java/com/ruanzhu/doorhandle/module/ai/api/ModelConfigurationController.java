package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.model.ModelConfigurationService;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import org.springframework.security.core.Authentication;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@RestController @RequestMapping("/api/agent/model-config")
@ConditionalOnProperty(prefix="agentscope.model-config",name="enabled",havingValue="true")
public class ModelConfigurationController {
    private final ModelConfigurationService service;
    public ModelConfigurationController(ModelConfigurationService service){this.service=service;}
    @ModelAttribute public void privateResponse(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    private void write(String marker,String site){if(!"update".equals(marker)||"cross-site".equals(site))throw new SecurityException();}
    public record Command(String requestId){}
    public record Restore(long baseRevision,String requestId){}
    public record Probe(String modelId,String requestId){}
    public record Revoke(long revision,String requestId){}
    @GetMapping public Object list(Authentication auth){var versions=service.list(AgentIdentity.from(auth));return Map.of("activeRevision",service.active().version(),"versions",versions);}
    @PostMapping("/{revision}/json-probe") public Object probe(Authentication auth,@PathVariable long revision,@RequestBody Probe input,@RequestHeader(value="X-Model-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);return service.probeJson(AgentIdentity.from(auth),revision,input.modelId(),input.requestId());}
    @PostMapping("/drafts") public Object draft(Authentication auth,@RequestBody ModelConfigurationService.Draft input,@RequestHeader(value="X-Model-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);return service.draft(AgentIdentity.from(auth),input);}
    @PostMapping("/{revision}/validate") public Object validate(Authentication auth,@PathVariable long revision,@RequestBody Command input,@RequestHeader(value="X-Model-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);return service.validate(AgentIdentity.from(auth),revision,input.requestId());}
    @PostMapping("/{revision}/publish") public Object publish(Authentication auth,@PathVariable long revision,@RequestBody Command input,@RequestHeader(value="X-Model-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);return service.publish(AgentIdentity.from(auth),revision,input.requestId());}
    @PostMapping("/{revision}/restore") public Object restore(Authentication auth,@PathVariable long revision,@RequestBody Restore input,@RequestHeader(value="X-Model-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);return service.restore(AgentIdentity.from(auth),revision,input.baseRevision(),input.requestId());}
    @PostMapping("/credentials/{provider}/revoke") public Object revoke(Authentication auth,@PathVariable String provider,@RequestBody Revoke input,@RequestHeader(value="X-Model-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);service.revoke(AgentIdentity.from(auth),provider,input.revision(),input.requestId());return Map.of("status","REVOKED");}
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> invalid(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).body(Map.of("message",error.getReason()));}
    @ExceptionHandler(SecurityException.class) public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","仅主管可管理模型配置"));}
    @ExceptionHandler({org.springframework.dao.DataAccessException.class,IllegalStateException.class}) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","模型配置结果尚未核对，请刷新版本状态"));}
    @ExceptionHandler({IllegalArgumentException.class,org.springframework.http.converter.HttpMessageNotReadableException.class}) public ResponseEntity<?> malformed(){return ResponseEntity.badRequest().body(Map.of("message","模型配置参数无效"));}
}
