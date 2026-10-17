package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.*;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class ConversationModelControllerTest {
    AgentWorkbenchService workbench;AgentModelService models;MockMvc mvc;
    UsernamePasswordAuthenticationToken auth(){var roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));return new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);}
    @BeforeEach void setup(){workbench=mock(AgentWorkbenchService.class);models=mock(AgentModelService.class);mvc=MockMvcBuilders.standaloneSetup(new ConversationModelController(workbench,models)).build();}
    @Test void modelSelectionRefusesCrossSiteAndUnmarkedChanges()throws Exception{
        String body="{\"requestId\":\"req\",\"revision\":0,\"modelId\":\"deepseek:demo\"}";
        mvc.perform(post("/api/agent/conversations/s1/model-selection").principal(auth()).contentType("application/json").content(body)).andExpect(status().isForbidden());
        mvc.perform(post("/api/agent/conversations/s1/model-selection").principal(auth()).header("X-Agent-Action","workbench").header("Sec-Fetch-Site","cross-site").contentType("application/json").content(body)).andExpect(status().isForbidden());verifyNoInteractions(workbench,models);
    }
    @Test void choiceOnlyAcceptsConfiguredServerCatalogAndReadsArePrivate()throws Exception{
        when(models.entries()).thenReturn(List.of(new AgentModelService.ModelInfo("deepseek:demo","deepseek","demo","CHAT_COMPLETIONS",true,false,"CLOSED",null,0),new AgentModelService.ModelInfo("missing","openai","missing","RESPONSES",false,false,"CLOSED",null,0)));
        when(workbench.selectModel(any(),eq("s1"),eq("deepseek:demo"),eq(0L),eq("req"),eq(Set.of("deepseek:demo")))).thenReturn(new AgentWorkbenchService.ModelSelection("deepseek:demo",1));
        mvc.perform(post("/api/agent/conversations/s1/model-selection").principal(auth()).header("X-Agent-Action","workbench").contentType("application/json").content("{\"requestId\":\"req\",\"revision\":0,\"modelId\":\"deepseek:demo\"}")).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.modelId").value("deepseek:demo"));
        mvc.perform(get("/api/agent/conversations/s1/model-selection").principal(auth())).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));verify(workbench).modelSelection(any(),eq("s1"));
    }
}
