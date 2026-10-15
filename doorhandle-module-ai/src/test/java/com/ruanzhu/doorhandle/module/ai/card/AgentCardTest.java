package com.ruanzhu.doorhandle.module.ai.card;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway;
import com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.tool.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.ObjectProvider;
import reactor.core.publisher.Mono;
import java.nio.file.Path;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class AgentCardTest {
    @TempDir Path workspace;
    final AgentActor actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    final DetectionAgentReadApi detection=mock(DetectionAgentReadApi.class);
    final QualityReportAgentApi reports=mock(QualityReportAgentApi.class);
    final BusinessUserDirectory users=mock(BusinessUserDirectory.class);
    final ObjectProvider<QualityReportAgentApi> provider=mock(ObjectProvider.class);
    final String reportId="qr-12345678-1234-1234-1234-123456789012";
    AgentCardService service(){when(provider.getIfAvailable()).thenReturn(reports);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));return new AgentCardService(detection,provider,users);}
    AgentCards.Reference tasks(String... ids){return new AgentCards.Reference("TASKS","get_task_detail",List.of(ids),null);}
    AgentTool fake(String name,ToolResultBlock result){return new AgentTool(){public String getName(){return name;}public String getDescription(){return "fixture";}public Map<String,Object> getParameters(){return Map.of();}public Mono<ToolResultBlock> callAsync(ToolCallParam p){return Mono.just(result);}};}
    void observe(AgentCardCollector c,String name,Map<String,Object> input,ToolResultBlock result){c.observe(fake(name,result)).callAsync(ToolCallParam.builder().input(input).build()).block(Duration.ofSeconds(3));}
    @Test void collectorOnlyAcceptsSuccessfulRegisteredBusinessResultsAndDeduplicatesReferences(){
        var c=new AgentCardCollector(json);
        for(var r:List.of(ToolResultBlock.error("{\"status\":\"OK\",\"source\":\"get_task_detail\",\"data\":{\"taskId\":\"task-1\"}}"),
                ToolResultBlock.text("模型说已经执行"),ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"forged\",\"data\":{\"taskId\":\"task-1\"}}"),
                ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"get_task_detail\",\"data\":{\"taskId\":\"javascript:alert(1)\"}}")))observe(c,"get_task_detail",Map.of(),r);
        assertThat(c.snapshot()).isEmpty();
        var success=ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"get_task_detail\",\"data\":{\"taskId\":\"task-1\",\"privatePath\":\"secret\"}}");
        observe(c,"get_task_detail",Map.of(),success.withState(ToolResultState.INTERRUPTED));assertThat(c.snapshot()).isEmpty();
        observe(c,"get_task_detail",Map.of(),success);observe(c,"get_task_detail",Map.of(),success);
        assertThat(c.snapshot()).containsExactly(tasks("task-1"));assertThat(c.snapshot().toString()).doesNotContain("secret");
        assertThat(new AgentCardCollector(json).snapshot()).isEmpty();
    }
    @Test void currentTaskScopeIsRecheckedAndRevokedRecordsDoNotLeakFromHistory(){
        var service=service();when(detection.task(actor,"own")).thenReturn(new DetectionAgentReadApi.TaskView("own","COMPLETED",null,"设备",2,2,0,"REVIEWED",null,null));
        when(detection.task(actor,"revoked")).thenThrow(new SecurityException("private task body"));
        var view=service.resolve(actor,List.of(tasks("own","revoked"))).get(0);
        assertThat(view.status()).isEqualTo("PARTIAL");assertThat(view.items()).hasSize(1);assertThat(view.toString()).doesNotContain("revoked","private task body");
        when(detection.task(actor,"own")).thenThrow(new SecurityException());
        assertThat(service.resolve(actor,List.of(tasks("own"))).get(0).items()).isEmpty();
        verifyNoInteractions(reports);
    }
    @Test void freshRolePreventsFormerSupervisorFromReadingEnterpriseStatistics(){
        var service=service();var staleBoss=new AgentActor(1,"alice",AgentActor.Role.SUPERVISOR);
        assertThat(service.resolve(staleBoss,List.of(new AgentCards.Reference("METRICS","get_department_work_metrics",List.of(),7))).get(0).status()).isEqualTo("UNAVAILABLE");
        verifyNoInteractions(detection,reports);
    }
    @Test void reportsOnlyExposeFreshSummaryAndNotNarrativeOrApprovalCredentials(){
        var service=service();when(reports.get(actor,reportId)).thenReturn(new QualityReportAgentApi.Detail(new QualityReportAgentApi.Summary(reportId,"task-1","<script>标题</script>","SUBMITTED",2,"alice"),"PRIVATE_NARRATIVE",Map.of("token","private"),"private reason",null,"javascript:bad"));
        var view=service.resolve(actor,List.of(new AgentCards.Reference("REPORTS","create_report_draft",List.of(reportId),null))).get(0);
        assertThat(view.toString()).contains("SUBMITTED").doesNotContain("PRIVATE_NARRATIVE","javascript:bad","private reason","token");
        when(reports.get(actor,reportId)).thenThrow(new com.ruanzhu.doorhandle.common.BusinessException(404,"private report"));
        assertThat(service.resolve(actor,List.of(new AgentCards.Reference("REPORTS","get_quality_report",List.of(reportId),null))).get(0).items()).isEmpty();
    }
    @Test void metricsHaveWhitelistedCountsAndNoInventedDefectRate(){
        var service=service();when(detection.metrics(actor,7)).thenReturn(new DetectionAgentReadApi.Metrics(Map.of("taskCount",2,"imageCount",9,"defectCount",12,"secret","private","defectRate",1.33),null,null,"OWNED_OR_ASSIGNED"));
        var view=service.resolve(actor,List.of(new AgentCards.Reference("METRICS","get_my_work_metrics",List.of(),7))).get(0);
        assertThat(view.metrics()).containsOnlyKeys("taskCount","imageCount","defectCount");assertThat(view.message()).contains("不等于");
    }
    @Test void realHarnessAndConversationCollectSpecialistResultDespiteModelInventedCardText() throws Exception {
        var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-card-fixture");var steps=new AtomicInteger();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{int step=steps.getAndIncrement();ContentBlock block;
            if(step==0)block=ToolUseBlock.builder().id("delegate-call").name("delegate_detection_task").input(Map.of("question","查询 task-1")).content("{\"question\":\"查询 task-1\"}").build();
            else if(step==1)block=ToolUseBlock.builder().id("task-call").name("get_task_detail").input(Map.of("taskId","task-1")).content("{\"taskId\":\"task-1\"}").build();
            else block=TextBlock.builder().text("模型虚构 card task-forged 不应形成引用").build();
            return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());});
        when(detection.task(actor,"task-1")).thenReturn(new DetectionAgentReadApi.TaskView("task-1","COMPLETED",null,"设备",2,2,1,null,null,null));
        var toolkit=new BusinessToolkitFactory(detection,mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json);
        var settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());
        var factory=new RoleAgentFactory(settings,toolkit,id->model);var service=new AgentScopeConversationService(factory,new AgentRunRegistry(),settings);
        var run=service.start(actor,"fixture",List.of(new AgentConversationApi.Message("user","查询 task-1")),"",event->{});
        assertThat(run.result().get(15,java.util.concurrent.TimeUnit.SECONDS)).contains("task-forged");
        assertThat(run.cards().get()).containsExactly(tasks("task-1"));assertThat(steps.get()).isEqualTo(4);
    }
}
