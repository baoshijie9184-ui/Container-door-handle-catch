package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.evolution.SkillLinkService;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.evolution.SkillEvolutionService;
import com.ruanzhu.doorhandle.module.ai.evolution.SkillDtos;
import jakarta.validation.Valid;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@RestController @RequestMapping("/api/agent/skills/links")
@ConditionalOnProperty(prefix="agentscope.evolution.links",name="enabled",havingValue="true")
public class SkillLinkController {
    private final SkillLinkService service;private final SkillEvolutionService evolution;
    public SkillLinkController(SkillLinkService service,SkillEvolutionService evolution){this.service=service;this.evolution=evolution;}
    @ModelAttribute public void noCache(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    @GetMapping public Object list(Authentication auth){return service.list(AgentIdentity.from(auth));}
    @GetMapping("/storage") public Object storage(Authentication auth){return service.storage(AgentIdentity.from(auth));}
    @GetMapping("/storage/audit") public Object cleanupAudit(Authentication auth){return service.cleanupAudit(AgentIdentity.from(auth));}
    @PostMapping("/downloads/{downloadId}/cleanup") public Object cleanup(Authentication auth,@PathVariable String downloadId,@Valid @RequestBody SkillLinkService.CleanupRequest request,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){guard(action);return service.cleanup(AgentIdentity.from(auth),downloadId,request);}
    @PostMapping public Object start(Authentication auth,@Valid @RequestBody SkillLinkService.Request request,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){guard(action);return service.start(AgentIdentity.from(auth),request);}
    @PostMapping("/{skillId}/upgrade") public Object upgrade(Authentication auth,@PathVariable String skillId,@Valid @RequestBody SkillLinkService.UpgradeRequest request,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){guard(action);return service.upgrade(AgentIdentity.from(auth),skillId,request);}
    @GetMapping("/{skillId}/compare") public Object compare(Authentication auth,@PathVariable String skillId,@RequestParam int fromVersion,@RequestParam int toVersion){return evolution.compareLinked(AgentIdentity.from(auth),skillId,fromVersion,toVersion);}
    @PostMapping("/{skillId}/uninstall") public Object uninstall(Authentication auth,@PathVariable String skillId,@Valid @RequestBody SkillDtos.Command request,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){guard(action);return evolution.uninstallLinked(AgentIdentity.from(auth),skillId,request);}
    private static void guard(String action){if(!"update".equals(action))throw new ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST,"缺少技能操作请求标记");}
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> conflict(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).body(Map.of("message",error.getReason()==null?"技能下载请求无效":error.getReason()));}
    @ExceptionHandler({org.springframework.web.bind.MethodArgumentNotValidException.class,org.springframework.http.converter.HttpMessageNotReadableException.class}) public ResponseEntity<?> invalid(){return ResponseEntity.badRequest().body(Map.of("message","链接下载参数或确认项不合法"));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","当前账号不能访问此下载"));}
    @ExceptionHandler(RuntimeException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","下载结果尚未核实，请刷新核对状态"));}
}
