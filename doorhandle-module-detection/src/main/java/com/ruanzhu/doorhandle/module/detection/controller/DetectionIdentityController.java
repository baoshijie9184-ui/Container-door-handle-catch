package com.ruanzhu.doorhandle.module.detection.controller;

import com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService;
import com.ruanzhu.doorhandle.contracts.security.BusinessPrincipal;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.*;
import java.util.Map;

@RestController @RequestMapping("/api/detection/identity")
@ConditionalOnProperty(prefix="detection.identity",name="enabled",havingValue="true")
public class DetectionIdentityController {
    private final DetectionIdentityService service;
    public DetectionIdentityController(DetectionIdentityService service){this.service=service;}
    private AgentActor actor(BusinessPrincipal principal){if(principal==null||principal.userId()==null||principal.userId()<1||principal.username()==null)throw new SecurityException();return new AgentActor(principal.userId(),principal.username(),AgentActor.Role.INSPECTOR);}
    private void write(String marker,String site){if(!"update".equals(marker)||"cross-site".equals(site))throw new SecurityException();}
    @GetMapping("/preview") public Object preview(@AuthenticationPrincipal BusinessPrincipal p,@RequestParam(defaultValue="") String after,@RequestParam(defaultValue="25") int size,@RequestParam(defaultValue="false") boolean includeAligned,@RequestParam(defaultValue="") String taskId){return service.preview(actor(p),after,size,includeAligned,taskId);}
    @GetMapping("/accounts") public Object accounts(@AuthenticationPrincipal BusinessPrincipal p,@RequestParam(defaultValue="") String keyword){return Map.of("records",service.accounts(actor(p),keyword));}
    @GetMapping("/commands/{request}") public Object command(@AuthenticationPrincipal BusinessPrincipal p,@PathVariable String request){return service.commandStatus(actor(p),request);}
    @GetMapping("/batches") public Object batches(@AuthenticationPrincipal BusinessPrincipal p,@RequestParam(defaultValue="0") long before,@RequestParam(defaultValue="10") int size){return service.history(actor(p),before,size);}
    @GetMapping("/reconciliations") public Object reconciliations(@AuthenticationPrincipal BusinessPrincipal p,@RequestParam(defaultValue="0") long before,@RequestParam(defaultValue="10") int size){return service.reconciliations(actor(p),before,size);}
    @GetMapping("/reconciliations/{request}") public Object reconciliation(@AuthenticationPrincipal BusinessPrincipal p,@PathVariable String request){return service.reconciliationStatus(actor(p),request);}
    @GetMapping("/reconciliations/{request}/items") public Object reconciliationItems(@AuthenticationPrincipal BusinessPrincipal p,@PathVariable String request,@RequestParam(defaultValue="0") long after,@RequestParam(defaultValue="50") int size){return service.reconciliationItems(actor(p),request,after,size);}
    @PostMapping("/reconciliations") public Object reconcile(@AuthenticationPrincipal BusinessPrincipal p,@RequestBody com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityReconciliationService.Create input,@RequestHeader(value="X-Identity-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);return service.reconcile(actor(p),input);}
    @PostMapping("/apply") public Object apply(@AuthenticationPrincipal BusinessPrincipal p,@RequestBody DetectionIdentityService.Apply input,@RequestHeader(value="X-Identity-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);return service.apply(actor(p),input);}
    public record Activate(long revision,String requestId,Boolean sourceProtection){public Activate(long revision,String requestId){this(revision,requestId,null);}}
    @PostMapping("/activate") public Object activate(@AuthenticationPrincipal BusinessPrincipal p,@RequestBody Activate input,@RequestHeader(value="X-Identity-Action",defaultValue="") String marker,@RequestHeader(value="Sec-Fetch-Site",defaultValue="") String site){write(marker,site);if(input==null)throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"缺少身份激活参数");service.activate(actor(p),input.revision(),input.requestId(),input.sourceProtection());return Map.of("mode","ACTIVE");}
    @ModelAttribute public void privateResponse(jakarta.servlet.http.HttpServletResponse response){response.setHeader("Cache-Control","no-store");}
    @ExceptionHandler(SecurityException.class) public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","仅主管可管理任务身份"));}
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<?> invalid(ResponseStatusException error){return ResponseEntity.status(error.getStatusCode()).body(Map.of("message",error.getReason()));}
    @ExceptionHandler(IllegalArgumentException.class) public ResponseEntity<?> changed(){return ResponseEntity.status(409).body(Map.of("message","目标账号资料已变化或选择无效，请重新选择并确认"));}
    @ExceptionHandler(org.springframework.dao.DataAccessException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("message","身份结果暂未核对，请刷新"));}
}
