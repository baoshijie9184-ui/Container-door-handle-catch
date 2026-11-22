package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.common.GlobalExceptionHandler;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.AgentApprovalMode;
import com.ruanzhu.doorhandle.module.ai.workbench.ConversationApprovalModes;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class ConversationApprovalModeControllerTest {
    private static final String ROUTE = "/api/agent/conversations/session/approval-mode";
    private static final String INPUT = """
            {"mode":"AUTO","revision":0,"requestId":"mode-request"}
            """;
    private static final AgentActor ACTOR = new AgentActor(7, "operator", AgentActor.Role.INSPECTOR);
    private final ConversationApprovalModes modes = mock(ConversationApprovalModes.class);
    private final org.springframework.test.web.servlet.MockMvc mvc = MockMvcBuilders
            .standaloneSetup(new ConversationApprovalModeController(modes)).setControllerAdvice(new GlobalExceptionHandler()).build();

    private UsernamePasswordAuthenticationToken auth() {
        var roles = List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
        return new UsernamePasswordAuthenticationToken(new TenantPrincipal(7L,"operator","",roles), null, roles);
    }

    @Test void selectionUsesAuthenticatedActorAndThePrivateVersionedContract() throws Exception {
        when(modes.read(ACTOR,"session")).thenReturn(new ConversationApprovalModes.Selection(AgentApprovalMode.DEFAULT,0));
        when(modes.select(ACTOR,"session",AgentApprovalMode.AUTO,0,"mode-request"))
                .thenReturn(new ConversationApprovalModes.Selection(AgentApprovalMode.AUTO,1));
        mvc.perform(get(ROUTE).principal(auth())).andExpect(status().isOk())
                .andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.mode").value("DEFAULT"));
        mvc.perform(post(ROUTE).principal(auth()).header("X-Agent-Action","workbench")
                .contentType("application/json").content(INPUT)).andExpect(status().isOk())
                .andExpect(header().string("Cache-Control","no-store"))
                .andExpect(jsonPath("$.mode").value("AUTO")).andExpect(jsonPath("$.revision").value(1));
    }

    @Test void crossSiteAndMalformedSettingsNeverReachPersistence() throws Exception {
        mvc.perform(post(ROUTE).principal(auth()).header("X-Agent-Action","workbench").header("Sec-Fetch-Site","cross-site")
                .contentType("application/json").content(INPUT)).andExpect(status().isForbidden());
        mvc.perform(post(ROUTE).principal(auth()).header("X-Agent-Action","workbench")
                .contentType("application/json").content(INPUT.replace("AUTO","UNRESTRICTED"))).andExpect(status().isBadRequest());
        verifyNoInteractions(modes);
    }

    @Test void ownerDenialAndRevisionConflictAreExplicit() throws Exception {
        when(modes.read(ACTOR,"session")).thenThrow(new SecurityException("private data"));
        mvc.perform(get(ROUTE).principal(auth())).andExpect(status().isForbidden())
                .andExpect(jsonPath("$.message").value("当前身份不能访问此会话的审批模式"));
        when(modes.select(ACTOR,"session",AgentApprovalMode.AUTO,0,"mode-request"))
                .thenThrow(new ResponseStatusException(HttpStatus.CONFLICT,"审批模式已变化，请刷新核对"));
        mvc.perform(post(ROUTE).principal(auth()).header("X-Agent-Action","workbench")
                .contentType("application/json").content(INPUT)).andExpect(status().isConflict());
    }
}
