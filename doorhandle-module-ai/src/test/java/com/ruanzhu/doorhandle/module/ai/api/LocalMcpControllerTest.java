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
    @Test void removalRequiresAuthenticationHeaderExplicitConsentAndMatchingTarget()throws Exception{
        String body="{\"expectedRevision\":2,\"operationId\":\"00000000-0000-0000-0000-000000000001\",\"confirmed\":true}";
        String path="/api/agent/mcp/fetch/registration/remove";
        mvc.perform(post(path).header("X-MCP-Action","update").contentType("application/json").content(body)).andExpect(status().isForbidden());
        mvc.perform(post(path).principal(auth).contentType("application/json").content(body)).andExpect(status().isBadRequest());
        for(String invalid:List.of(body.replace("true","false"),body.replace(",\"confirmed\":true",""),body.replace("00000000-0000-0000-0000-000000000001","other"),body.replace("\"expectedRevision\":2,",""),body.replace("\"expectedRevision\":2","\"expectedRevision\":-1")))
            mvc.perform(post(path).principal(auth).header("X-MCP-Action","update").contentType("application/json").content(invalid)).andExpect(status().isBadRequest());
        verifyNoInteractions(service);
        when(service.removeRegistration(any(),eq(2),anyString(),eq(true))).thenReturn(Map.of("status","UNINSTALLED","enabled",false));
        mvc.perform(post(path).principal(auth).header("X-MCP-Action","update").contentType("application/json").content(body))
            .andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.status").value("UNINSTALLED")).andExpect(jsonPath("$.enabled").value(false));
        verify(service).removeRegistration(argThat(actor->actor.userId()==1),eq(2),eq("00000000-0000-0000-0000-000000000001"),eq(true));
    }
    @Test void cancelRequiresOwnerAuthenticationActionHeaderAndExplicitConfirmedTarget()throws Exception{
        String body="{\"expectedRevision\":1,\"operationId\":\"00000000-0000-0000-0000-000000000001\",\"confirmed\":true}";
        mvc.perform(post("/api/agent/mcp/fetch/install/cancel").header("X-MCP-Action","update").contentType("application/json").content(body)).andExpect(status().isForbidden());
        mvc.perform(post("/api/agent/mcp/fetch/install/cancel").principal(auth).contentType("application/json").content(body)).andExpect(status().isBadRequest());
        for(String invalid:List.of(body.replace("true","false"),body.replace("00000000-0000-0000-0000-000000000001","../other"),body.replace("\"expectedRevision\":1,","")))
            mvc.perform(post("/api/agent/mcp/fetch/install/cancel").principal(auth).header("X-MCP-Action","update").contentType("application/json").content(invalid)).andExpect(status().isBadRequest());
        verifyNoInteractions(service);
        when(service.cancelInstallation(any(),eq(1),anyString(),eq(true))).thenReturn(Map.of("status","CANCELLED","enabled",false));
        mvc.perform(post("/api/agent/mcp/fetch/install/cancel").principal(auth).header("X-MCP-Action","update").contentType("application/json").content(body))
                .andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.status").value("CANCELLED")).andExpect(jsonPath("$.enabled").value(false));
        verify(service).cancelInstallation(argThat(actor->actor.userId()==1),eq(1),eq("00000000-0000-0000-0000-000000000001"),eq(true));
    }
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
