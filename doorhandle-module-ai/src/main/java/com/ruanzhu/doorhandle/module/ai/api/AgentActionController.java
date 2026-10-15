package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.action.AgentActionService;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.config.AgentActionProperties;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.*;

@RestController
@RequestMapping("/api/agent/actions")
@Tag(name="Agent 操作确认",description="当前账号的已存提议与审计；客户端不得提供工具参数或执行结果")
public class AgentActionController {
    private final AgentActionService actions;
    private final AgentActionProperties properties;
    public AgentActionController(AgentActionService actions) {this(actions,new AgentActionProperties());}
    @org.springframework.beans.factory.annotation.Autowired
    public AgentActionController(AgentActionService actions,AgentActionProperties properties) {this.actions=actions;this.properties=properties;}
    @GetMapping public List<AgentActionService.View> list(Authentication auth,@RequestParam(required=false) String sessionId,
            @RequestParam(required=false) String runId,@RequestParam(defaultValue="50") int limit) {return actions.list(AgentIdentity.from(auth),sessionId,runId,limit);}
    @GetMapping("/{id}") public AgentActionService.View get(Authentication auth,@PathVariable String id) {return actions.get(AgentIdentity.from(auth),id);}
    @GetMapping("/{id}/audit") public List<AgentActionService.Audit> audit(Authentication auth,@PathVariable String id) {return actions.audit(AgentIdentity.from(auth),id);}
    @PostMapping("/{id}/confirm") public AgentActionService.View confirm(Authentication auth,@PathVariable String id,@RequestBody Map<String,Object> body,
            @RequestHeader(value="X-Agent-Action",defaultValue="") String header,
            @RequestHeader(value="Origin",required=false) String origin,@RequestHeader(value="Sec-Fetch-Site",required=false) String fetchSite) {
        trustedOrigin(origin,fetchSite);
        if (!"confirm".equals(header) || body==null || !body.keySet().equals(Set.of("decision","version"))
                || !(body.get("decision") instanceof String decision) || !(body.get("version") instanceof Number version)
                || !Double.isFinite(version.doubleValue()) || version.doubleValue()!=version.longValue()) throw bad();
        return actions.decide(AgentIdentity.from(auth),id,version.longValue(),decision);
    }
    @PostMapping("/{id}/cancel") public AgentActionService.View cancel(Authentication auth,@PathVariable String id,@RequestBody Map<String,Object> body,
            @RequestHeader(value="X-Agent-Action",defaultValue="") String header,
            @RequestHeader(value="Origin",required=false) String origin,@RequestHeader(value="Sec-Fetch-Site",required=false) String fetchSite) {
        trustedOrigin(origin,fetchSite);
        if (!"cancel".equals(header) || body==null || !body.keySet().equals(Set.of("version")) || !(body.get("version") instanceof Number v)
                || !Double.isFinite(v.doubleValue()) || v.doubleValue()!=v.longValue()) throw bad();
        return actions.decide(AgentIdentity.from(auth),id,v.longValue(),"CANCEL");
    }
    private static ResponseStatusException bad() {return new ResponseStatusException(HttpStatus.BAD_REQUEST,"确认请求只允许决策、版本及指定请求头");}
    private void trustedOrigin(String origin,String fetchSite) {
        if ((origin!=null&&!properties.getAllowedOrigins().contains(origin))||"cross-site".equals(fetchSite))
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,"确认请求来源不被允许");
    }
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> invalid(ResponseStatusException error) {return ResponseEntity.status(error.getStatusCode()).body(Map.of("message",Objects.toString(error.getReason(),"请求无效")));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) public ResponseEntity<?> denied() {return ResponseEntity.status(403).body(Map.of("message","当前身份没有操作权限"));}
    @ExceptionHandler({org.springframework.dao.DataAccessException.class,IllegalStateException.class}) public ResponseEntity<?> unavailable() {return ResponseEntity.status(503).body(Map.of("message","确认未完成，请刷新操作状态后再试"));}
}
