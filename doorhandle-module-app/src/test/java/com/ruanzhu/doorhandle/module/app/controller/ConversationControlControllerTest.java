package com.ruanzhu.doorhandle.module.app.controller;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.app.service.ChatSessionService;
import com.ruanzhu.doorhandle.module.app.service.impl.ConversationInboxService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.List;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
class ConversationControlControllerTest {
    ConversationInboxService inbox;AgentConversationControlApi controls;ChatSessionService sessions;MockMvc mvc;
    UsernamePasswordAuthenticationToken auth(){var roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));return new UsernamePasswordAuthenticationToken(new TenantPrincipal(1L,"alice","",roles),null,roles);}
    @BeforeEach void setup(){inbox=mock(ConversationInboxService.class);controls=mock(AgentConversationControlApi.class);sessions=mock(ChatSessionService.class);
        var provider=mock(ObjectProvider.class);when(provider.getIfAvailable()).thenReturn(inbox);when(provider.getObject()).thenReturn(inbox);
        var controlProvider=mock(ObjectProvider.class);when(controlProvider.getIfAvailable()).thenReturn(controls);when(controlProvider.getObject()).thenReturn(controls);
        mvc=MockMvcBuilders.standaloneSetup(new ConversationControlController(provider,controlProvider,sessions)).build();}
    @Test void capabilityReadIsPrivateAndNeverExecutesAnything()throws Exception{mvc.perform(get("/api/agent/conversations/capabilities").principal(auth())).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.enabled").value(true));verifyNoInteractions(inbox);}
    @Test void promotionUsesTheExistingMessageVersionAndRunAndRequiresTheActionHeader()throws Exception{
        String path="/api/agent/conversations/s1/inputs/existing-message/steer",body="{\"runId\":\"run-1\",\"revision\":3}";
        mvc.perform(post(path).principal(auth()).contentType("application/json").content(body)).andExpect(status().isForbidden());verifyNoInteractions(inbox);
        mvc.perform(post(path).principal(auth()).header("X-Agent-Action","conversation-control").contentType("application/json").content(body)).andExpect(status().isOk());
        verify(inbox).steer(new AgentActor(1L,"alice",AgentActor.Role.INSPECTOR),"s1","existing-message",3,"run-1");verify(inbox,never()).enqueue(any(),anyString(),anyString(),anyString(),anyString(),anyString());
    }
    @Test void foreignSessionIsRejectedBeforeReadingTheInbox()throws Exception{doThrow(new com.ruanzhu.doorhandle.common.BusinessException(404,"会话不存在")).when(sessions).verifySessionOwner("alice","foreign");mvc.perform(get("/api/agent/conversations/foreign/control").principal(auth())).andExpect(status().isNotFound());verifyNoInteractions(inbox);}
    @Test void queueMutationNeedsTheActionHeaderAndRefusesCrossSiteRequests()throws Exception{
        String body="{\"id\":\"00000000-0000-0000-0000-000000000001\",\"mode\":\"NEXT_TURN\",\"content\":\"question\"}";
        mvc.perform(post("/api/agent/conversations/s1/inputs").principal(auth()).contentType("application/json").content(body)).andExpect(status().isForbidden());
        mvc.perform(post("/api/agent/conversations/s1/inputs").principal(auth()).header("X-Agent-Action","conversation-control").header("Sec-Fetch-Site","cross-site").contentType("application/json").content(body)).andExpect(status().isForbidden());verifyNoInteractions(inbox);
    }
    @Test void cancellationRequiresExplicitConfirmationAndDoesNotImplicitlyRemoveQueuedMessages()throws Exception{
        mvc.perform(post("/api/agent/conversations/s1/control").principal(auth()).header("X-Agent-Action","conversation-control").contentType("application/json").content("{\"runId\":\"run-1\",\"action\":\"cancel\",\"revision\":0}")).andExpect(status().isBadRequest());verify(controls,never()).command(any(),anyString(),anyString(),anyString(),anyLong());
    }
    @Test void storageFailuresHaveNoPrivateSqlOrMessageDetails()throws Exception{when(inbox.list(any(),anyString())).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("PRIVATE_SQL_AND_TEXT"));mvc.perform(get("/api/agent/conversations/s1/control").principal(auth())).andExpect(status().isServiceUnavailable()).andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("PRIVATE_SQL_AND_TEXT"))));}
    @Test void revokedIdentityReturnsForbiddenWithoutItsInternalReason()throws Exception{when(inbox.list(any(),anyString())).thenThrow(new SecurityException("PRIVATE_IDENTITY_DETAILS"));mvc.perform(get("/api/agent/conversations/s1/control").principal(auth())).andExpect(status().isForbidden()).andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("PRIVATE_IDENTITY_DETAILS"))));}
}
