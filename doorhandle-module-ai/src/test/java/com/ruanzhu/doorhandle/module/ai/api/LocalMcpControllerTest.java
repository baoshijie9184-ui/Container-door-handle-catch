package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.mcp.LocalMcpService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class LocalMcpControllerTest {
    final LocalMcpService service=mock(LocalMcpService.class);
    final org.springframework.test.web.servlet.MockMvc mvc=MockMvcBuilders.standaloneSetup(new LocalMcpController(service)).build();
    final List<SimpleGrantedAuthority> roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
    final UsernamePasswordAuthenticationToken auth=new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);
    @Test void anonymousAndMissingHeaderOrConsentCannotInstall()throws Exception{
        mvc.perform(get("/api/agent/mcp/fetch")).andExpect(status().isForbidden());
        String content="{\"expectedRevision\":0,\"requestId\":\"request-one\",\"licenseAccepted\":true}";
        mvc.perform(post("/api/agent/mcp/fetch/install").principal(auth).contentType("application/json").content(content)).andExpect(status().isBadRequest());
        mvc.perform(post("/api/agent/mcp/fetch/install").principal(auth).header("X-MCP-Action","update").contentType("application/json").content(content.replace("true","false"))).andExpect(status().isBadRequest());verifyNoInteractions(service);
        mvc.perform(post("/api/agent/mcp/fetch/enabled").principal(auth).header("X-MCP-Action","update").contentType("application/json").content("{\"expectedRevision\":2}")).andExpect(status().isBadRequest());verifyNoInteractions(service);
    }
    @Test void directoryIsPrivateUncachedAndInstallReturnsAsyncAcceptedStatus()throws Exception{
        when(service.view(any())).thenReturn(Map.of("status","NOT_INSTALLED"));mvc.perform(get("/api/agent/mcp/fetch").principal(auth)).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));
        when(service.install(any(),eq(0),eq("request-one"),eq(true))).thenReturn(Map.of("status","INSTALLING","enabled",false));
        mvc.perform(post("/api/agent/mcp/fetch/install").principal(auth).header("X-MCP-Action","update").contentType("application/json").content("{\"expectedRevision\":0,\"requestId\":\"request-one\",\"licenseAccepted\":true}"))
            .andExpect(status().isAccepted()).andExpect(jsonPath("$.enabled").value(false));
        mvc.perform(get("/api/agent/mcp/arbitrary").principal(auth)).andExpect(status().isNotFound());
    }
}
