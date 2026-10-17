package com.ruanzhu.doorhandle.module.app.controller;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.app.service.impl.AgentWorkspaceService;
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

class AgentWorkbenchControllerTest {
    AgentWorkbenchApi api;AgentWorkspaceService workspace;MockMvc mvc;
    UsernamePasswordAuthenticationToken auth(){var roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));return new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);}
    @BeforeEach void setup(){api=mock(AgentWorkbenchApi.class);workspace=mock(AgentWorkspaceService.class);when(api.capabilities()).thenReturn(Map.of("enabled",true,"files",true,"forks",true));mvc=MockMvcBuilders.standaloneSetup(new AgentWorkbenchController(api,workspace)).build();}
    @Test void capabilityReadRequiresLoginAndDoesNotTriggerExecution()throws Exception{mvc.perform(get("/api/agent/workbench/capabilities")).andExpect(status().isUnauthorized());mvc.perform(get("/api/agent/workbench/capabilities").principal(auth())).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store"));verify(api,never()).command(any(),anyString(),anyString(),anyLong(),anyString(),anyString(),anyMap());}
    @Test void commandsRequireExplicitActionHeaderAndRefuseCrossSiteRequests()throws Exception{
        String path="/api/agent/conversations/s1/workbench/item",body="{\"requestId\":\"req\",\"revision\":1,\"action\":\"answer\",\"input\":{\"answer\":\"A\"}}";
        mvc.perform(post(path).principal(auth()).contentType("application/json").content(body)).andExpect(status().isForbidden());mvc.perform(post(path).principal(auth()).header("X-Agent-Action","workbench").header("Sec-Fetch-Site","cross-site").contentType("application/json").content(body)).andExpect(status().isForbidden());verifyNoInteractions(api);
    }
    @Test void foreignSessionIsRejectedBeforeAWorkflowMutation()throws Exception{doThrow(new SecurityException("PRIVATE_REASON")).when(workspace).assertOwned(any(),eq("foreign"));mvc.perform(post("/api/agent/conversations/foreign/workbench/item").principal(auth()).header("X-Agent-Action","workbench").contentType("application/json").content("{\"requestId\":\"req\",\"revision\":0,\"action\":\"cancel\"}")).andExpect(status().isForbidden()).andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("PRIVATE_REASON"))));verify(api,never()).command(any(),anyString(),anyString(),anyLong(),anyString(),anyString(),anyMap());}
    @Test void fileDeliveryIsPrivateAndDisablesContentSniffing()throws Exception{String id="00000000-0000-0000-0000-000000000001";when(workspace.requireFile(any(),eq("s1"),eq(id))).thenReturn(new WorkbenchSessionApi.File(id,"notes.html","text/plain; charset=utf-8",8,"hash","uploads"));when(workspace.bytes(any(),eq("s1"),eq(id))).thenReturn("<script>".getBytes());mvc.perform(get("/api/agent/conversations/s1/files/"+id+"/content").principal(auth())).andExpect(status().isOk()).andExpect(header().string("X-Content-Type-Options","nosniff")).andExpect(header().string("Cache-Control","no-store")).andExpect(header().string("Content-Security-Policy","default-src 'none'; sandbox")).andExpect(content().contentTypeCompatibleWith("text/plain"));}
    @Test void forkRequiresACompletedCutPointBeforeCopyingAnything()throws Exception{doThrow(new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"仍在执行")).when(api).assertForkPoint(any(),eq("s1"),eq(2L));mvc.perform(post("/api/agent/conversations/s1/fork").principal(auth()).header("X-Agent-Action","workbench").contentType("application/json").content("{\"requestId\":\"req\",\"throughMessageId\":2}")).andExpect(status().isConflict());verify(workspace,never()).fork(any(),anyString(),anyLong(),anyString());}
    @Test void pdfPagePreviewRequiresLoginAndFreshSessionPermission()throws Exception{
        String path="/api/agent/conversations/s1/files/pdf/preview";
        mvc.perform(get(path)).andExpect(status().isUnauthorized());verify(workspace,never()).previewPdf(any(),anyString(),anyString(),anyInt());
        when(workspace.previewPdf(any(),eq("s1"),eq("pdf"),eq(2))).thenReturn(new AgentWorkspaceService.PdfPreview(new byte[]{1,2,3},2,3));
        mvc.perform(get(path).param("page","2").principal(auth())).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(header().string("X-Content-Type-Options","nosniff")).andExpect(header().string("X-PDF-Page","2")).andExpect(header().string("X-PDF-Pages","3")).andExpect(content().contentType("image/png"));
        doThrow(new SecurityException("private")).when(workspace).assertOwned(any(),eq("s1"));
        mvc.perform(get(path).principal(auth())).andExpect(status().isForbidden());
        when(api.capabilities()).thenReturn(Map.of("files",false));mvc.perform(get(path).principal(auth())).andExpect(status().isConflict());
    }
}
