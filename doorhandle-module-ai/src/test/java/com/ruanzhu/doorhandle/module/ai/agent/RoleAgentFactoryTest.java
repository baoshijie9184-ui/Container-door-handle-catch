package com.ruanzhu.doorhandle.module.ai.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import io.agentscope.core.model.Model;
import io.agentscope.core.model.ModelRegistry;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.security.access.AccessDeniedException;
import java.nio.file.Path;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class RoleAgentFactoryTest {
    @TempDir Path workspace;
    private final AgentActor employee = new AgentActor(1, "alice", AgentActor.Role.INSPECTOR);
    private final AgentActor supervisor = new AgentActor(2, "boss", AgentActor.Role.SUPERVISOR);

    @Test void mainActuallyDelegatesThroughSpecialistToolkitToBusinessFacade() {
        var model = mock(Model.class);
        when(model.getModelName()).thenReturn("role-toolkit-test");
        var responses = new java.util.concurrent.atomic.AtomicInteger();
        when(model.stream(anyList(), anyList(), any())).thenAnswer(invocation -> {
            int step = responses.getAndIncrement();
            io.agentscope.core.message.ContentBlock content = switch (step) {
                case 0 -> io.agentscope.core.message.ToolUseBlock.builder().id("delegate-1")
                        .name("delegate_detection_task").input(java.util.Map.of("question", "查询本人检测任务"))
                        .content("{\"question\":\"查询本人检测任务\"}").build();
                case 1 -> io.agentscope.core.message.ToolUseBlock.builder().id("query-1")
                        .name("get_my_detection_tasks").input(java.util.Map.of()).build();
                default -> io.agentscope.core.message.TextBlock.builder().text("本人暂无检测任务").build();
            };
            return reactor.core.publisher.Flux.just(io.agentscope.core.model.ChatResponse.builder()
                    .id("response-" + step).content(java.util.List.of(content)).build());
        });
        ModelRegistry.register("role-toolkit-test", model);
        var properties = new AgentScopeProperties();
        properties.setModel("role-toolkit-test");
        properties.setWorkspace(workspace.toString());
        var detection = mock(DetectionAgentReadApi.class);
        when(detection.tasks(employee, 1, 20, false)).thenReturn(new DetectionAgentReadApi.TaskPage(java.util.List.of(), 0, 1, 20));
        var factory = new RoleAgentFactory(properties, new BusinessToolkitFactory(detection,
                mock(ResourceAgentReadApi.class), mock(ModelAgentReadApi.class), new ObjectMapper()));
        try (var main = (io.agentscope.harness.agent.HarnessAgent) factory.create(employee, null)) {
            var result = main.call("查询本人任务").block(java.time.Duration.ofSeconds(15));
            assertThat(result.getTextContent()).contains("暂无检测任务");
        }
        verify(detection).tasks(employee, 1, 20, false);
        assertThat(responses.get()).isEqualTo(4);
    }
    @Test void taskSpecificQueryUsesTaskFacadeWithoutSubstitutingCompanyMetrics() {
        for(var actor:java.util.List.of(employee,supervisor)) {
            String specialist=actor.supervisor()?"detection-quality":"detection-task";
            var model=mock(Model.class);when(model.getModelName()).thenReturn("task-detail-fixture");var step=new java.util.concurrent.atomic.AtomicInteger();
            when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
                io.agentscope.core.message.ContentBlock block=switch(step.getAndIncrement()){
                    case 0->io.agentscope.core.message.ToolUseBlock.builder().id("delegate-task").name("delegate_"+specialist.replace('-','_')).input(java.util.Map.of("question","只读查询任务 det_abc 的状态和缺陷总数")).content("{\"question\":\"只读查询任务 det_abc 的状态和缺陷总数\"}").build();
                    case 1->io.agentscope.core.message.ToolUseBlock.builder().id("task-detail").name("get_task_detail").input(java.util.Map.of("taskId","det_abc")).content("{\"taskId\":\"det_abc\"}").build();
                    default->io.agentscope.core.message.TextBlock.builder().text("任务 det_abc 已完成，缺陷总数 3；未提供类别分布").build();
                };
                return reactor.core.publisher.Flux.just(io.agentscope.core.model.ChatResponse.builder().content(java.util.List.of(block)).build());
            });
            var detection=mock(DetectionAgentReadApi.class);when(detection.task(actor,"det_abc")).thenReturn(new DetectionAgentReadApi.TaskView("det_abc","COMPLETED","PENDING_REVIEW","camera-1",1,1,3,"PENDING",null,null));
            var settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());var toolkit=new BusinessToolkitFactory(detection,mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper());
            try(var main=(io.agentscope.harness.agent.HarnessAgent)new RoleAgentFactory(settings,toolkit,id->model).create(actor,null)){
                var delegate=main.getToolkit().getTool("delegate_"+specialist.replace('-','_'));assertThat(delegate.getDescription()).contains("get_task_detail");
                assertThat(main.call("只读查询 det_abc 的状态和缺陷总数").block(java.time.Duration.ofSeconds(15)).getTextContent()).contains("缺陷总数 3");
            }
            verify(detection).task(actor,"det_abc");verify(detection,never()).metrics(any(),anyInt());verifyNoMoreInteractions(detection);
        }
    }

    @Test void supervisorProposalRunsThroughAgentScopeButStaffCannotRegisterIt() {
        var actions=mock(com.ruanzhu.doorhandle.module.ai.action.AgentActionService.class);
        when(actions.enabled()).thenReturn(true);
        var command=new DetectionAssignmentApi.Command("task-1","站点A","alice",null,null);
        var pending=new com.ruanzhu.doorhandle.module.ai.action.AgentActionService.View("action-1","run-1","session-1","ASSIGN_QUALITY_TASK","PENDING",1,command,new DetectionAssignmentApi.Values(null,null,null,null,"DETECTED"),null,null,null,null);
        when(actions.propose(eq(supervisor),eq("run-1"),eq("proposal-1"),eq(command))).thenReturn(pending);
        var model=mock(Model.class);when(model.getModelName()).thenReturn("proposal-fixture");
        var step=new java.util.concurrent.atomic.AtomicInteger();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
            io.agentscope.core.message.ContentBlock block=switch(step.getAndIncrement()) {
                case 0->io.agentscope.core.message.ToolUseBlock.builder().id("delegate-1").name("delegate_detection_quality").input(java.util.Map.of("question","提出任务质检分配")).content("{\"question\":\"提出任务质检分配\"}").build();
                case 1->io.agentscope.core.message.ToolUseBlock.builder().id("proposal-1").name("propose_quality_assignment").input(java.util.Map.of("taskId","task-1","qualityStation","站点A","assignee","alice")).content("{\"taskId\":\"task-1\",\"qualityStation\":\"站点A\",\"assignee\":\"alice\"}").build();
                default->io.agentscope.core.message.TextBlock.builder().text("提议待确认，尚未分配").build();
            };
            return reactor.core.publisher.Flux.just(io.agentscope.core.model.ChatResponse.builder().content(java.util.List.of(block)).build());
        });
        var settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());
        var toolkit=new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper(),actions);
        var factory=new RoleAgentFactory(settings,toolkit,id->model);
        var run=mock(com.ruanzhu.doorhandle.module.ai.journal.AgentJournal.Run.class);when(run.id()).thenReturn("run-1");
        try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(supervisor,null,new com.ruanzhu.doorhandle.module.ai.journal.AgentJournalMiddleware(run,supervisor,true))) {
            assertThat(agent.call("将任务分配给员工").block(java.time.Duration.ofSeconds(10)).getTextContent()).contains("尚未分配");
        }
        verify(actions).propose(supervisor,"run-1","proposal-1",command);
        assertThat(factory.definitions(employee)).allSatisfy(def->assertThat(def.tools()).doesNotContain("propose_quality_assignment"));
        assertThatThrownBy(()->toolkit.create(employee,factory.definitions(supervisor).get(0),"run-1")).isInstanceOf(SecurityException.class);
    }
    private RoleAgentFactory factory() {
        var properties = new AgentScopeProperties();
        properties.setWorkspace(workspace.toString());
        return new RoleAgentFactory(properties, new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),
                mock(ResourceAgentReadApi.class), mock(ModelAgentReadApi.class), new ObjectMapper()));
    }
    @Test void roleAndInternalAgentRequestsAreCheckedBeforeModelCreation() {
        var factory = factory();
        assertThat(factory.resolveMainId(employee, "doorhandle-assistant")).isEqualTo("employee-main");
        assertThat(factory.resolveMainId(supervisor, "supervisor-assistant")).isEqualTo("supervisor-main");
        assertThatThrownBy(() -> factory.create(employee, "supervisor-main")).isInstanceOf(AccessDeniedException.class);
        assertThatThrownBy(() -> factory.create(employee, "model-ops")).isInstanceOf(AccessDeniedException.class);
    }
    @Test void mainAgentsHaveOnlyFourExplicitDelegatesAndNeverShareInstances() {
        try (var models = mockStatic(ModelRegistry.class)) {
            models.when(() -> ModelRegistry.resolve(anyString())).thenReturn(mock(Model.class));
            var factory = factory();
            for (var actor : new AgentActor[]{employee, supervisor}) {
                try (var first = (io.agentscope.harness.agent.HarnessAgent) factory.create(actor, null);
                        var second = (io.agentscope.harness.agent.HarnessAgent) factory.create(actor, null)) {
                    assertThat(first).isNotSameAs(second);
                    assertThat(first.getToolkit()).isNotSameAs(second.getToolkit());
                    assertThat(first.getToolkit().getToolNames()).containsExactlyInAnyOrderElementsOf(
                            RoleAgentCatalog.specialists(actor).stream().map(d -> "delegate_" + d.id().replace('-', '_')).toList());
                }
            }
        }
    }
}
