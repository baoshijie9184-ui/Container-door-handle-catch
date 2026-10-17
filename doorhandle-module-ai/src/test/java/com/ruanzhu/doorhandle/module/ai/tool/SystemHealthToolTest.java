package com.ruanzhu.doorhandle.module.ai.tool;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.tool.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Path;
import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SystemHealthToolTest {
    @TempDir Path workspace;
    final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);
    final AgentActor employee=new AgentActor(2,"staff",AgentActor.Role.INSPECTOR);
    final SystemHealthReadApi health=mock(SystemHealthReadApi.class);
    BusinessToolkitFactory toolkit(){return new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper().findAndRegisterModules(),null,null,health);}
    RoleAgentCatalog.Definition definition(){return RoleAgentCatalog.specialists(boss).stream().filter(d->d.id().equals("resource-management")).findFirst().orElseThrow();}
    SystemHealthReadApi.Snapshot snapshot(){return new SystemHealthReadApi.Snapshot("DOWN",List.of(new SystemHealthReadApi.Component("db","DOWN","ACTUATOR")),List.of("kafka","mem0"),Instant.EPOCH,Instant.EPOCH.plusSeconds(30));}
    @Test void healthQueryIsReadonlyAcceptsNoArgumentsAndHasNoEmployeeRegistration(){
        var tool=toolkit().create(boss,definition()).getTool("get_system_health");
        assertThat(tool.isReadOnly()).isTrue();assertThat(tool.getParameters()).containsEntry("additionalProperties",false).containsEntry("properties",Map.of());
        for(var input:List.<Map<String,Object>>of(Map.of("url","http://private"),Map.of("command","docker restart"),Map.of("userId",9),Map.of("force",true)))
            assertThat(tool.callAsync(ToolCallParam.builder().input(input).build()).block().getState()).isEqualTo(ToolResultState.ERROR);
        verifyNoInteractions(health);
        assertThat(RoleAgentCatalog.specialists(employee)).allSatisfy(d->assertThat(d.tools()).doesNotContain("get_system_health"));
        assertThatThrownBy(()->toolkit().create(employee,definition())).isInstanceOf(SecurityException.class);
        when(health.snapshot(boss)).thenReturn(snapshot());
        var result=tool.callAsync(ToolCallParam.builder().input(Map.of()).build()).block();
        assertThat(result.getOutput().toString()).contains("get_system_health","notMonitored","DOWN","checkedAt","expiresAt");verify(health).snapshot(boss);
    }
    @Test void unavailableProbeFacadeAndErrorsNeverProduceHealthyOrLeakedDetails(){
        var tool=toolkit().create(boss,definition()).getTool("get_system_health");
        when(health.snapshot(boss)).thenThrow(new IllegalStateException("PRIVATE_CONNECTION_ERROR"));
        var result=tool.callAsync(ToolCallParam.builder().input(Map.of()).build()).block();
        assertThat(result.getState()).isEqualTo(ToolResultState.ERROR);assertThat(result.getOutput().toString()).doesNotContain("PRIVATE_","UP");
        var absent=new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),new ObjectMapper());
        assertThat(absent.create(boss,definition()).getTool("get_system_health").callAsync(ToolCallParam.builder().input(Map.of()).build()).block().getState()).isEqualTo(ToolResultState.ERROR);
    }
    @Test void realHarnessDelegatesHealthQueryAndAuditsOnlyCallMetadata(){
        when(health.snapshot(boss)).thenReturn(snapshot());var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-health-query");var steps=new AtomicInteger();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{int step=steps.getAndIncrement();ContentBlock block;
            if(step==0)block=ToolUseBlock.builder().id("delegate-health").name("delegate_resource_management").input(Map.of("question","PRIVATE_HEALTH_QUESTION")).content("{\"question\":\"PRIVATE_HEALTH_QUESTION\"}").build();
            else if(step==1)block=ToolUseBlock.builder().id("health-query").name("get_system_health").input(Map.of()).content("{}").build();
            else block=TextBlock.builder().text("数据库探针报告异常 Kafka 与 Mem0 未覆盖检查").build();
            return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());});
        var properties=new AgentScopeProperties();properties.setWorkspace(workspace.toString());var factory=new RoleAgentFactory(properties,toolkit(),id->model);
        var run=mock(AgentJournal.Run.class);var events=new ArrayList<Map<String,Object>>();doAnswer(inv->{events.add(inv.getArgument(1));return null;}).when(run).event(anyString(),anyMap());
        try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(boss,null,new AgentJournalMiddleware(run,boss))){
            assertThat(agent.call("查询系统健康").block(Duration.ofSeconds(15)).getTextContent()).contains("未覆盖");
        }
        verify(health).snapshot(boss);assertThat(steps.get()).isEqualTo(4);
        assertThat(events).anySatisfy(e->{assertThat(e.get("tool")).isEqualTo("get_system_health");assertThat(e.get("parentCallId")).isEqualTo("delegate-health");});
        assertThat(events.toString()).doesNotContain("PRIVATE_HEALTH_QUESTION","checkedAt","notMonitored");
    }
}
