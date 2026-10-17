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
    @Test void alertToolsBindSupervisorAndExposeStrictSchemasWithSafeDefaults() {
        var definition=RoleAgentCatalog.specialists(supervisor).stream().filter(d->d.id().equals("resource-management")).findFirst().orElseThrow();
        var toolkit=factory.create(supervisor,definition);
        var tool=toolkit.getTool("list_device_alerts");
        when(resources.alerts(eq(supervisor),any())).thenReturn(new ResourceAgentReadApi.AlertPage(List.of(),null,false,java.time.LocalDateTime.now()));
        var result=tool.callAsync(ToolCallParam.builder().input(Map.of()).build()).block();
        assertThat(result.getOutput().toString()).contains("list_device_alerts","queriedAt").doesNotContain("runtimeSnapshot");
        verify(resources).alerts(supervisor,new ResourceAgentReadApi.AlertQuery("OPEN","ALL",null,null,20));
        tool.callAsync(ToolCallParam.builder().input(Map.of("status","ALL","level","CRITICAL","deviceId","9","beforeId","9223372036854775807","size",5)).build()).block();
        verify(resources).alerts(supervisor,new ResourceAgentReadApi.AlertQuery("ALL","CRITICAL","9","9223372036854775807",5));
        assertThat(tool.isReadOnly()).isTrue();assertThat(toolkit.getTool("get_device_alert").isReadOnly()).isTrue();
        assertThat(tool.getParameters()).containsEntry("additionalProperties",false);
        assertThat(RoleAgentCatalog.specialists(employee)).allSatisfy(d->assertThat(d.tools()).doesNotContain("list_device_alerts","get_device_alert"));
    }
    @Test void malformedAlertFiltersAndSpoofedIdentityNeverReachResourceFacade() {
        var definition=RoleAgentCatalog.specialists(supervisor).stream().filter(d->d.id().equals("resource-management")).findFirst().orElseThrow();
        var toolkit=factory.create(supervisor,definition);var list=toolkit.getTool("list_device_alerts");
        for(var input:List.<Map<String,Object>>of(Map.of("status","open"),Map.of("level","ALARM"),Map.of("deviceId",9),Map.of("beforeId","01"),
                Map.of("beforeId","9223372036854775808"),Map.of("beforeId",1.5),Map.of("page",2),Map.of("size",101),Map.of("userId",8),Map.of("role","SUPERVISOR"))) {
            var result=list.callAsync(ToolCallParam.builder().input(input).build()).block();
            assertThat(result.getState()).isEqualTo(io.agentscope.core.message.ToolResultState.ERROR);
        }
        for(Object id:List.of(7,"0","01","ALERT-code","9223372036854775808","../secret")) {
            var result=toolkit.getTool("get_device_alert").callAsync(ToolCallParam.builder().input(Map.of("alertId",id)).build()).block();
            assertThat(result.getState()).isEqualTo(io.agentscope.core.message.ToolResultState.ERROR);
        }
        verifyNoInteractions(resources);
    }
    @Test void alertDetailUsesPrimaryKeyAndDoesNotExposeDatabaseErrorBodies() {
        var definition=RoleAgentCatalog.specialists(supervisor).stream().filter(d->d.id().equals("resource-management")).findFirst().orElseThrow();
        var tool=factory.create(supervisor,definition).getTool("get_device_alert");
        when(resources.alert(supervisor,7)).thenReturn(new ResourceAgentReadApi.AlertView("7","ALERT-CODE",null,"LINE-A","CAPTURE_EXCEPTION","MAJOR","OPEN",null,null));
        assertThat(tool.callAsync(ToolCallParam.builder().input(Map.of("alertId","7")).build()).block().getOutput().toString()).contains("ALERT-CODE");
        verify(resources).alert(supervisor,7);
        when(resources.alert(supervisor,7)).thenThrow(new IllegalStateException("jdbc:PRIVATE_DATABASE_PASSWORD"));
        assertThat(tool.callAsync(ToolCallParam.builder().input(Map.of("alertId","7")).build()).block().getOutput().toString()).doesNotContain("PRIVATE_DATABASE_PASSWORD");
    }
    @Test void detectionModelOperationsUseStrictPrimaryKeyAndNeverRegisterWritesOrEmployeeAccess(){
        var definition=RoleAgentCatalog.specialists(supervisor).stream().filter(d->d.id().equals("model-ops")).findFirst().orElseThrow();
        var toolkit=factory.create(supervisor,definition);var tool=toolkit.getTool("get_model_operations");
        assertThat(toolkit.getToolNames()).containsExactlyInAnyOrder("list_models","get_model_operations");
        assertThat(tool.isReadOnly()).isTrue();assertThat(tool.getParameters()).containsEntry("additionalProperties",false);
        assertThat(RoleAgentCatalog.specialists(employee)).allSatisfy(d->assertThat(d.tools()).doesNotContain("get_model_operations"));
        for(var input:List.<Map<String,Object>>of(Map.of(),Map.of("modelId",7),Map.of("modelId","0"),Map.of("modelId","01"),
                Map.of("modelId","2147483648"),Map.of("modelId","../7"),Map.of("modelId","7","userId",8),Map.of("modelId","7","publish",true))) {
            var result=tool.callAsync(ToolCallParam.builder().input(input).build()).block();
            assertThat(result.getState()).isEqualTo(io.agentscope.core.message.ToolResultState.ERROR);
        }
        verifyNoInteractions(models);
        var record=new ModelAgentReadApi.Operations(new ModelAgentReadApi.ModelView(7,"六类检测","v2","PUBLISHED",true),null,null,
                new ModelAgentReadApi.Evaluation(null,null,null,null,null,null),new ModelAgentReadApi.Rollout("CANARY",0,null,null),
                new ModelAgentReadApi.Usage(0,null,null),java.time.LocalDateTime.now(),List.of());
        when(models.operations(supervisor,7)).thenReturn(record);
        var result=tool.callAsync(ToolCallParam.builder().input(Map.of("modelId","7")).build()).block();
        assertThat(result.getOutput().toString()).contains("get_model_operations","configuredPercent","六类检测");verify(models).operations(supervisor,7);
        when(models.operations(supervisor,7)).thenThrow(new IllegalStateException("PRIVATE_MODEL_PATH"));
        assertThat(tool.callAsync(ToolCallParam.builder().input(Map.of("modelId","7")).build()).block().getOutput().toString()).doesNotContain("PRIVATE_MODEL_PATH");
    }
}
