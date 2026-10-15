package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.market.AgentMarketCatalog;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/api/agent/markets")
public class AgentMarketController {
    private final AgentMarketCatalog service;
    public AgentMarketController(AgentMarketCatalog service) { this.service = service; }

    @GetMapping
    public ResponseEntity<AgentMarketCatalog.Catalog> catalog(Authentication authentication) {
        AgentIdentity.from(authentication);
        return ResponseEntity.ok().header("Cache-Control", "no-store").body(service.catalog());
    }

    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<?> denied() {
        return ResponseEntity.status(403).header("Cache-Control", "no-store")
            .body(Map.of("message", "请使用具备检测助手权限的账号登录"));
    }
}
