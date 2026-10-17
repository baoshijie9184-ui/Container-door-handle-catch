package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import com.ruanzhu.doorhandle.module.ai.workbench.AgentWorkbenchService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.common.GlobalExceptionHandler;
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
    @BeforeEach void setup(){workbench=mock(AgentWorkbenchService.class);models=mock(AgentModelService.class);mvc=MockMvcBuilders.standaloneSetup(new ConversationModelController(workbench,models)).setControllerAdvice(new GlobalExceptionHandler()).build();}
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
    @Test void expectedErrorsKeepHttpStatusWithGlobalAdvice()throws Exception{
        when(workbench.modelSelection(any(),eq("foreign"))).thenThrow(new SecurityException("private owner data"));
        mvc.perform(get("/api/agent/conversations/foreign/model-selection").principal(auth())).andExpect(status().isForbidden()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.message").value("当前身份不能访问此会话的模型选择"));
        when(workbench.selectModel(any(),anyString(),anyString(),anyLong(),anyString(),anySet())).thenThrow(new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"模型选择已变化，请刷新核对"));
        mvc.perform(post("/api/agent/conversations/s1/model-selection").principal(auth()).header("X-Agent-Action","workbench").contentType("application/json").content("{\"requestId\":\"req\",\"revision\":0,\"modelId\":\"\"}")).andExpect(status().isConflict()).andExpect(jsonPath("$.message").value("模型选择已变化，请刷新核对"));
    }
    @Test void invalidInputAndStorageFailureAreExplicitAndSanitized()throws Exception{
        mvc.perform(post("/api/agent/conversations/s1/model-selection").principal(auth()).header("X-Agent-Action","workbench").contentType("application/json").content("{\"revision\":-1}")).andExpect(status().isBadRequest());
        when(workbench.modelSelection(any(),eq("s1"))).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("private JDBC connection"));
        mvc.perform(get("/api/agent/conversations/s1/model-selection").principal(auth())).andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.message").value("模型选择结果暂不可核对，请刷新后确认"));
    }
}
