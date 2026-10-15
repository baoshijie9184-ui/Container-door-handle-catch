package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.market.AgentMarketCatalog;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AgentMarketControllerTest {
    final org.springframework.test.web.servlet.MockMvc mvc = MockMvcBuilders
        .standaloneSetup(new AgentMarketController(new AgentMarketCatalog())).build();

    private UsernamePasswordAuthenticationToken account(String role) {
        var roles = List.of(new SimpleGrantedAuthority(role));
        return new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L, "alice", "", roles), null, roles);
    }

    @Test void bothBusinessRolesCanReadWithoutReceivingRuntimeAuthorization() throws Exception {
        for (String role : List.of("ROLE_INSPECTOR", "ROLE_SUPERVISOR")) {
            mvc.perform(get("/api/agent/markets").principal(account(role)))
                .andExpect(status().isOk()).andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.integrationStatus").value("DIRECTORY_ONLY"))
                .andExpect(jsonPath("$.markets.length()").value(11));
        }
    }

    @Test void anonymousAndUnsupportedRoleCannotReadCatalogAndThereIsNoInstallEndpoint() throws Exception {
        mvc.perform(get("/api/agent/markets")).andExpect(status().isForbidden())
            .andExpect(header().string("Cache-Control", "no-store"));
        mvc.perform(get("/api/agent/markets").principal(account("ROLE_UNKNOWN"))).andExpect(status().isForbidden());
        mvc.perform(post("/api/agent/markets").principal(account("ROLE_SUPERVISOR")))
            .andExpect(status().isMethodNotAllowed());
    }
}
