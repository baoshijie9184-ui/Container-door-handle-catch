package com.ruanzhu.doorhandle.module.ai.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentCatalog;
import io.agentscope.core.tool.ToolCallParam;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class BusinessToolkitFactoryTest {
    private final DetectionAgentReadApi detection = mock(DetectionAgentReadApi.class);
    private final ResourceAgentReadApi resources = mock(ResourceAgentReadApi.class);
    private final ModelAgentReadApi models = mock(ModelAgentReadApi.class);
    private final BusinessToolkitFactory factory = new BusinessToolkitFactory(detection, resources, models,
            new ObjectMapper().findAndRegisterModules());
    private final AgentActor employee = new AgentActor(1, "alice", AgentActor.Role.INSPECTOR);
    private final AgentActor supervisor = new AgentActor(2, "boss", AgentActor.Role.SUPERVISOR);

    @Test void allEightToolkitsHaveExactWhitelistsAndAreReadOnly() {
        for (var actor : List.of(employee, supervisor)) {
            for (var definition : RoleAgentCatalog.specialists(actor)) {
                var toolkit = factory.create(actor, definition);
                assertThat(toolkit.getToolNames()).containsExactlyInAnyOrderElementsOf(definition.tools());
                for (String name : toolkit.getToolNames()) assertThat(toolkit.getTool(name).isReadOnly()).isTrue();
            }
        }
        assertThatThrownBy(() -> factory.create(employee, RoleAgentCatalog.specialists(supervisor).get(1)))
                .isInstanceOf(SecurityException.class);
    }
    @Test void asyncToolsKeepServerBoundIdentityAndRejectSpoofedIdentity() {
        when(detection.tasks(employee, 1, 20, false)).thenReturn(new DetectionAgentReadApi.TaskPage(List.of(), 0, 1, 20));
        var tool = factory.create(employee, RoleAgentCatalog.specialists(employee).get(0)).getTool("get_my_detection_tasks");
        tool.callAsync(ToolCallParam.builder().input(Map.of()).build()).block();
        verify(detection).tasks(employee, 1, 20, false);
        clearInvocations(detection);
        tool.callAsync(ToolCallParam.builder().input(Map.of("userId", 2, "role", "SUPERVISOR")).build()).block();
        verifyNoInteractions(detection);
    }
    @Test void invalidPagingNeverReachesTheDatabaseFacade() {
        var tool = factory.create(employee, RoleAgentCatalog.specialists(employee).get(0)).getTool("get_my_detection_tasks");
        for (Object value : List.of(0, -1, 1.5, 10001, "1")) {
            tool.callAsync(ToolCallParam.builder().input(Map.of("page", value)).build()).block();
        }
        verifyNoInteractions(detection);
    }
    @Test void toolErrorsDoNotExposeInternalExceptionDetails() {
        when(detection.tasks(employee, 1, 20, false)).thenThrow(new IllegalStateException("jdbc:secret-password"));
        var tool = factory.create(employee, RoleAgentCatalog.specialists(employee).get(0)).getTool("get_my_detection_tasks");
        var result = tool.callAsync(ToolCallParam.builder().input(Map.of()).build()).block();
        assertThat(result.getOutput().toString()).doesNotContain("secret-password");
    }
}
