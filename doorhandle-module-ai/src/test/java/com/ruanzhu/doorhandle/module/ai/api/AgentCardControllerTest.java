package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.card.AgentCardService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class AgentCardControllerTest {
    final AgentCardService service=mock(AgentCardService.class);
    final org.springframework.test.web.servlet.MockMvc mvc=MockMvcBuilders.standaloneSetup(new AgentCardController(service)).build();
    final List<SimpleGrantedAuthority> roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
    final UsernamePasswordAuthenticationToken auth=new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);
    @Test void malformedOrSpoofedCardInputsAreRejectedBeforeBusinessReads() throws Exception {
        for(String input:List.of("{\"cards\":[],\"userId\":2}","{\"cards\":[{\"type\":\"TASKS\",\"tool\":\"get_task_detail\",\"ids\":[\"task-1\"],\"html\":\"<script>\"}]}",
                "{\"cards\":[{\"type\":\"METRICS\",\"tool\":\"get_my_work_metrics\",\"ids\":[],\"days\":1.5}]}",
                "{\"cards\":[{\"type\":\"TASKS\",\"tool\":\"approve_report\",\"ids\":[\"task-1\"]}]}",
                "{\"cards\":[{\"type\":\"TASKS\",\"tool\":\"get_task_detail\",\"ids\":[\"../secret\"]}]}")) {
            mvc.perform(post("/api/agent/cards/resolve").principal(auth).contentType("application/json").content(input)).andExpect(status().isBadRequest());
        }
        verifyNoInteractions(service);
    }
    @Test void validReadUsesServerIdentityAndDisablesCaching() throws Exception {
        when(service.resolve(any(),anyList())).thenReturn(List.of());
        mvc.perform(post("/api/agent/cards/resolve").principal(auth).contentType("application/json").content("{\"cards\":[]}"))
                .andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.cards").isArray());
        verify(service).resolve(eq(new com.ruanzhu.doorhandle.contracts.agent.AgentActor(1,"alice",com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.INSPECTOR)),eq(List.of()));
    }
    @Test void anonymousRequestCannotReachBusinessAndStorageErrorsAreSanitized() throws Exception {
        mvc.perform(post("/api/agent/cards/resolve").contentType("application/json").content("{\"cards\":[]}")).andExpect(status().isForbidden());
        verifyNoInteractions(service);
        when(service.resolve(any(),anyList())).thenThrow(new IllegalStateException("sk-private jdbc password"));
        mvc.perform(post("/api/agent/cards/resolve").principal(auth).contentType("application/json").content("{\"cards\":[]}"))
                .andExpect(status().isServiceUnavailable()).andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("sk-private"))));
    }
}
