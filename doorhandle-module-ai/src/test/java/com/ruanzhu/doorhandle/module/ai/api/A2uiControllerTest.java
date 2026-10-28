package com.ruanzhu.doorhandle.module.ai.api;

import com.ruanzhu.doorhandle.module.ai.ui.A2uiService;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class A2uiControllerTest {
    @Test void dynamicUiWiresWithoutOptionalWorkbenchAndDisappearsWhenAiIsDisabled(){
        var runner=new org.springframework.boot.test.context.runner.ApplicationContextRunner()
                .withBean(com.ruanzhu.doorhandle.module.ai.card.AgentCardService.class,()->mock(com.ruanzhu.doorhandle.module.ai.card.AgentCardService.class))
                .withBean(com.ruanzhu.doorhandle.contracts.agent.AgentChatSessionApi.class,()->mock(com.ruanzhu.doorhandle.contracts.agent.AgentChatSessionApi.class))
                .withBean(com.fasterxml.jackson.databind.ObjectMapper.class,com.fasterxml.jackson.databind.ObjectMapper::new)
                .withUserConfiguration(A2uiController.class,A2uiService.class);
        runner.withPropertyValues("agentscope.ai.enabled=true","agentscope.workbench.enabled=false").run(context->{
            org.assertj.core.api.Assertions.assertThat(context).hasSingleBean(A2uiController.class).hasSingleBean(A2uiService.class)
                    .doesNotHaveBean(com.ruanzhu.doorhandle.contracts.agent.WorkbenchSessionApi.class);
        });
        runner.withPropertyValues("agentscope.ai.enabled=false").run(context->org.assertj.core.api.Assertions.assertThat(context)
                .doesNotHaveBean(A2uiController.class).doesNotHaveBean(A2uiService.class));
    }
    private UsernamePasswordAuthenticationToken auth(){var roles=List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR"));return new UsernamePasswordAuthenticationToken(new TenantPrincipal(19L,"supervisor.demo","",roles),null,roles);}
    private String query(){return "\"sessionId\":\"s1\",\"cards\":[{\"type\":\"TASKS\",\"tool\":\"get_task_detail\",\"ids\":[\"task-1\"],\"days\":null}]";}
    @Test void usesAuthenticatedActorAndNeverCachesPrivateSurface()throws Exception{
        var service=mock(A2uiService.class);when(service.resolve(any(),any())).thenReturn(Map.of("version","v0.9.1","messages",List.of()));var mvc=MockMvcBuilders.standaloneSetup(new A2uiController(service)).build();
        mvc.perform(post("/agui/ui/resolve").principal(auth()).contentType("application/json").content("{"+query()+"}" )).andExpect(status().isOk()).andExpect(header().string("Cache-Control","no-store")).andExpect(jsonPath("$.version").value("v0.9.1"));
        verify(service).resolve(argThat(actor->actor.userId()==19&&actor.supervisor()),any());
    }
    @Test void requiresExplicitInteractionHeaderAndMapsPreparedQuestion()throws Exception{
        var service=mock(A2uiService.class);when(service.followUp(any(),any())).thenReturn("继续分析任务");var mvc=MockMvcBuilders.standaloneSetup(new A2uiController(service)).build();
        String body="{"+query()+",\"action\":{\"name\":\"FOLLOW_UP\",\"surfaceId\":\"s1\",\"sourceComponentId\":\"followup-0\",\"timestamp\":\"2026-10-28T03:00:00Z\",\"context\":{\"question\":\"继续分析\",\"referenceIndex\":0}}}";
        mvc.perform(post("/agui/ui/actions").principal(auth()).contentType("application/json").content(body)).andExpect(status().isBadRequest());verifyNoInteractions(service);
        mvc.perform(post("/agui/ui/actions").principal(auth()).header("X-Agent-Action","a2ui").contentType("application/json").content(body)).andExpect(status().isOk()).andExpect(jsonPath("$.question").value("继续分析任务"));
    }
    @Test void deniesMissingAuthenticationAndSanitizesPrivateFailures()throws Exception{
        var service=mock(A2uiService.class);var mvc=MockMvcBuilders.standaloneSetup(new A2uiController(service)).build();
        mvc.perform(post("/agui/ui/resolve").contentType("application/json").content("{"+query()+"}" )).andExpect(status().isForbidden());verifyNoInteractions(service);
        when(service.resolve(any(),any())).thenThrow(new IllegalStateException("PRIVATE_KEY"));
        mvc.perform(post("/agui/ui/resolve").principal(auth()).contentType("application/json").content("{"+query()+"}" )).andExpect(status().isServiceUnavailable()).andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("PRIVATE_KEY"))));
    }
}
