package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.action.AgentActionService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.mockito.Mockito.*;

class AgentActionControllerTest {
    @Test void rejectsMissingIntentHeaderExtraParametersAndNonIntegerVersions() throws Exception {
        var service=mock(AgentActionService.class);var mvc=MockMvcBuilders.standaloneSetup(new AgentActionController(service)).build();
        var roles=List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR"));
        var auth=new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"boss","",roles),null,roles);
        mvc.perform(post("/api/agent/actions/action-1/confirm").principal(auth).contentType("application/json").content("{\"decision\":\"APPROVE\",\"version\":1}")).andExpect(status().isBadRequest());
        for(var body:List.of("{\"decision\":\"APPROVE\",\"version\":1,\"assignee\":\"evil\"}","{\"decision\":\"APPROVE\",\"version\":1.5}","{\"decision\":\"APPROVE\",\"version\":\"1\"}"))
            mvc.perform(post("/api/agent/actions/action-1/confirm").principal(auth).header("X-Agent-Action","confirm").contentType("application/json").content(body)).andExpect(status().isBadRequest());
        verifyNoInteractions(service);
    }
    @Test void rejectsForeignOriginAndCrossSiteFetchBeforeBusinessExecution() throws Exception {
        var service=mock(AgentActionService.class);var mvc=MockMvcBuilders.standaloneSetup(new AgentActionController(service)).build();
        for(var header:List.of("Origin","Sec-Fetch-Site"))
            mvc.perform(post("/api/agent/actions/action-1/confirm").header(header,header.equals("Origin")?"https://foreign.invalid":"cross-site")
                    .header("X-Agent-Action","confirm").contentType("application/json").content("{\"decision\":\"APPROVE\",\"version\":1}")).andExpect(status().isForbidden());
        verifyNoInteractions(service);
    }
}
