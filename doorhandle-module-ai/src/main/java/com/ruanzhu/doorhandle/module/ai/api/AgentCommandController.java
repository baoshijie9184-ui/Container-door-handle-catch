package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@ConditionalOnProperty(prefix="agentscope.ai",name="enabled",havingValue="true")
public class AgentCommandController {
    private final RoleAgentFactory factory;
    public AgentCommandController(RoleAgentFactory factory){this.factory=factory;}
    @GetMapping("/api/agent/commands") public ResponseEntity<?> catalog(Authentication auth){return ResponseEntity.ok().header("Cache-Control","no-store").body(factory.slashCommands().catalog(AgentIdentity.from(auth)));}
    @ExceptionHandler({SecurityException.class,org.springframework.security.access.AccessDeniedException.class}) public ResponseEntity<?> denied(){return ResponseEntity.status(403).header("Cache-Control","no-store").body(Map.of("message","请登录后查看当前账号的技能命令"));}
    @ExceptionHandler(RuntimeException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).header("Cache-Control","no-store").body(Map.of("message","技能命令目录暂不可用 请稍后刷新"));}
}
