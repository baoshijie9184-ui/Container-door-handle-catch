package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.evolution.*;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import jakarta.validation.Valid;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import java.util.Map;

@RestController @RequestMapping("/api/agent/skills")
@ConditionalOnProperty(prefix="agentscope.evolution",name="enabled",havingValue="true")
public class SkillEvolutionController {
    private final SkillEvolutionService service;
    public SkillEvolutionController(SkillEvolutionService service){this.service=service;}
    @ModelAttribute public void noCache(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    @GetMapping public Object list(Authentication auth){return service.list(AgentIdentity.from(auth));}
    @GetMapping("/{id}") public Object get(Authentication auth,@PathVariable String id){return service.get(AgentIdentity.from(auth),id);}
    @GetMapping("/sources") public Object sources(Authentication auth){return service.sources(AgentIdentity.from(auth));}
    /** 旧地址明确告知已移除，避免通用异常处理将不存在的上传请求包装成 HTTP 200。 */
    @RequestMapping(value={"/imports","/imports/tool-options"}) public ResponseEntity<?> removedImports(Authentication auth){
        AgentIdentity.from(auth);return ResponseEntity.status(org.springframework.http.HttpStatus.GONE).body(Map.of("message","Skill ZIP 上传功能已移除"));
    }
    @PostMapping("/sources/{runId}/consent") public Object capture(Authentication auth,@PathVariable String runId,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){write(action);return service.capture(AgentIdentity.from(auth),runId);}
    @PostMapping public Object create(Authentication auth,@Valid @RequestBody SkillDtos.Draft draft,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){write(action);return service.create(AgentIdentity.from(auth),draft);}
    @PostMapping("/{id}/versions") public Object revise(Authentication auth,@PathVariable String id,@RequestParam int expectedRevision,@Valid @RequestBody SkillDtos.Draft draft,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){write(action);return service.revise(AgentIdentity.from(auth),id,expectedRevision,draft);}
    @PostMapping("/{id}/eval") public Object evaluate(Authentication auth,@PathVariable String id,@RequestBody Revision command,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){write(action);return service.evaluate(AgentIdentity.from(auth),id,command.expectedRevision());}
    @PostMapping("/{id}/submit") public Object submit(Authentication auth,@PathVariable String id,@RequestBody Revision command,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){write(action);return service.submit(AgentIdentity.from(auth),id,command.expectedRevision());}
    @PostMapping("/{id}/decision") public Object decide(Authentication auth,@PathVariable String id,@Valid @RequestBody SkillDtos.Decision command,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){write(action);return service.decide(AgentIdentity.from(auth),id,command);}
    @PostMapping("/{id}/rollback") public Object rollback(Authentication auth,@PathVariable String id,@Valid @RequestBody SkillDtos.Rollback command,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){write(action);return service.rollback(AgentIdentity.from(auth),id,command);}
    @PostMapping("/{id}/archive") public Object archive(Authentication auth,@PathVariable String id,@Valid @RequestBody SkillDtos.Command command,@RequestHeader(value="X-Skill-Action",defaultValue="") String action){write(action);return service.archive(AgentIdentity.from(auth),id,command);}
    public record Revision(int expectedRevision) {}
    private void write(String action){if(!"update".equals(action))throw new ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST,"技能操作请求格式不正确");}
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> conflict(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).header("Cache-Control","no-store").body(Map.of("message",error.getReason()==null?"技能请求无效":error.getReason()));}
    @ExceptionHandler({org.springframework.web.bind.MethodArgumentNotValidException.class,org.springframework.http.converter.HttpMessageNotReadableException.class,
            org.springframework.web.bind.MissingServletRequestParameterException.class,org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class}) public ResponseEntity<?> invalid(){return ResponseEntity.badRequest().body(Map.of("message","技能参数或人工核对项不合法"));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","当前身份不能访问技能资料"));}
    @ExceptionHandler(RuntimeException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","技能操作结果尚未核实 请刷新状态后核对"));}
}
