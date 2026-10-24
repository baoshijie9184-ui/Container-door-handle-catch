package com.ruanzhu.doorhandle.module.system.controller;

import com.ruanzhu.doorhandle.module.system.service.OperationsAuditService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;
import java.util.Map;

@RestController @RequestMapping("/api/operations/audit")
@ConditionalOnProperty(prefix="operations.audit",name="enabled",havingValue="true")
public class OperationsAuditController {
    private final OperationsAuditService service;
    @org.springframework.beans.factory.annotation.Autowired private org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.system.service.FileDeliveryAuditService> deliveries;
    public OperationsAuditController(OperationsAuditService service){this.service=service;}
    @GetMapping("/deliveries") public ResponseEntity<?> deliveries(@AuthenticationPrincipal TenantPrincipal principal,@RequestParam(defaultValue="9223372036854775807") long before,@RequestParam(defaultValue="50") int size){if(principal==null)throw new SecurityException();var api=deliveries.getIfAvailable();return ResponseEntity.ok().header("Cache-Control","no-store").body(api==null?java.util.List.of():api.list(new AgentActor(principal.userId(),principal.username(),AgentActor.Role.INSPECTOR),before,size));}
    @GetMapping public ResponseEntity<?> list(@AuthenticationPrincipal TenantPrincipal principal,@RequestParam(defaultValue="9223372036854775807") long before,@RequestParam(defaultValue="50") int size,@RequestParam(required=false) String domain){if(principal==null)throw new SecurityException();return ResponseEntity.ok().header("Cache-Control","no-store").body(service.list(new AgentActor(principal.userId(),principal.username(),AgentActor.Role.INSPECTOR),before,size,domain));}
    @ExceptionHandler(SecurityException.class) public ResponseEntity<?> denied(){return ResponseEntity.status(403).body(Map.of("message","无权读取审计"));}
    @ExceptionHandler(IllegalArgumentException.class) public ResponseEntity<?> invalid(){return ResponseEntity.badRequest().body(Map.of("message","请核对审计查询参数"));}
}
