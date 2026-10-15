package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.context.AgentIdentity;
import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Read-only model catalog, without credentials, endpoints or custom headers. */
@RestController
@ConditionalOnProperty(prefix = "agentscope.ai", name = "enabled", havingValue = "true")
public class AgentModelController {
    private final AgentModelService models;
    public AgentModelController(AgentModelService models) { this.models = models; }
    @GetMapping("${agentscope.agui.path-prefix:/agui}/models")
    public AgentModelService.Catalog catalog(Authentication auth) {
        AgentIdentity.from(auth);
        return models.catalog();
    }
}
