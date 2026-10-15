package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.command.AgentSlashCommands;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AgentCommandControllerTest {
    @Test void commandCatalogRequiresIdentityIsPrivateAndDoesNotBuildAgent()throws Exception {
        var factory=mock(RoleAgentFactory.class);var commands=mock(AgentSlashCommands.class);when(factory.slashCommands()).thenReturn(commands);when(commands.catalog(any())).thenReturn(Map.of("commands",List.of(),"skills",List.of()));
        var mvc=MockMvcBuilders.standaloneSetup(new AgentCommandController(factory)).build();var roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));var auth=new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);
        mvc.perform(get("/api/agent/commands").principal(auth)).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));
        mvc.perform(get("/api/agent/commands")).andExpect(status().isForbidden());verify(commands,times(1)).catalog(any());verify(factory,never()).create(any(),any());
    }
}
