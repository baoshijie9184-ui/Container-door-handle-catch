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
    final ResourceAgentReadApi resources=mock(ResourceAgentReadApi.class);
    final ModelAgentReadApi models=mock(ModelAgentReadApi.class);
    final ObjectProvider<QualityReportAgentApi> provider=mock(ObjectProvider.class);
    final String reportId="qr-12345678-1234-1234-1234-123456789012";
    AgentCardService service(){when(provider.getIfAvailable()).thenReturn(reports);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));return new AgentCardService(detection,provider,users,resources,models);}
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
    @Test void resourceCollectorUsesOnlyStableIdsFromSuccessfulToolArraysAndCapsEachCard() throws Exception {
        var c=new AgentCardCollector(json);
        var devices=new ArrayList<Map<String,Object>>();
        for(int i=1;i<=7;i++)devices.add(Map.of("deviceId",String.valueOf(i),"deviceCode","different-code-"+i,"path","private"));
        observe(c,"list_devices",Map.of(),ToolResultBlock.text(json.writeValueAsString(Map.of("status","OK","source","list_devices","data",devices))));
        observe(c,"list_models",Map.of(),ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"list_models\",\"data\":[{\"modelId\":2147483647,\"modelPath\":\"private\"}]}"));
        observe(c,"list_models",Map.of(),ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"list_models\",\"data\":[{\"modelId\":2147483648}]}"));
        observe(c,"list_devices",Map.of(),ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"list_devices\",\"data\":[{\"deviceId\":\"../secrets\"}]}"));
        assertThat(c.snapshot()).containsExactly(new AgentCards.Reference("DEVICES","list_devices",List.of("1","2","3","4","5"),null),new AgentCards.Reference("MODELS","list_models",List.of("2147483647"),null));
        assertThat(c.snapshot().toString()).doesNotContain("private","different-code");
        var restored=json.readValue(json.writeValueAsString(new AgentCards.Envelope(1,"完成","run-1",c.snapshot())),AgentCards.Envelope.class);
        assertThat(restored.cards()).isEqualTo(c.snapshot());
    }
    @Test void supervisorResourceCardsRefreshCurrentStateAndNeverSurviveRoleRevocation(){
        var service=service();var boss=new AgentActor(1,"alice",AgentActor.Role.SUPERVISOR);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",true));
        var refs=List.of(new AgentCards.Reference("DEVICES","list_devices",List.of("9"),null),new AgentCards.Reference("MODELS","list_models",List.of("7"),null));
        when(resources.device(boss,9L)).thenReturn(new ResourceAgentReadApi.DeviceView("9","CODE-OTHER","IDLE","ONLINE","CONNECTED","CONNECTED","STOPPED"));
        when(models.model(boss,7)).thenReturn(new ModelAgentReadApi.ModelView(7,"检测模型","v2","PUBLISHED",true));
        assertThat(service.resolve(boss,refs)).allMatch(v->v.status().equals("OK")&&v.scope().equals("SINGLE_ENTERPRISE"));
        when(models.model(boss,7)).thenThrow(new com.ruanzhu.doorhandle.common.BusinessException(404,"private-model-path"));
        var unavailable=service.resolve(boss,refs).get(1);
        assertThat(unavailable.items()).isEmpty();assertThat(unavailable.status()).isEqualTo("PARTIAL");assertThat(unavailable.toString()).doesNotContain("private-model-path");
        clearInvocations(resources,models);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        assertThat(service.resolve(boss,refs)).allMatch(v->v.status().equals("UNAVAILABLE")&&v.items().isEmpty());
        verifyNoInteractions(resources,models);
    }
    @Test void resourceReferencesRejectWrongToolsAndNonCanonicalOrOverflowingIds(){
        for(String id:List.of("0","-1","01","1.0","1e2","9223372036854775808","../secret"))
            assertThatThrownBy(()->new AgentCards.Reference("DEVICES","list_devices",List.of(id),null)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->new AgentCards.Reference("MODELS","list_models",List.of("2147483648"),null)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->new AgentCards.Reference("DEVICES","list_models",List.of("1"),null)).isInstanceOf(IllegalArgumentException.class);
        assertThat(new AgentCards.Reference("DEVICES","list_devices",List.of("9223372036854775807"),null).ids()).containsExactly("9223372036854775807");
    }
    @Test void alertCardsOnlyPersistTrustedIdsAndRefreshCurrentStatusWithoutRevivingRevokedAccess() throws Exception {
        var service=service();var boss=new AgentActor(1,"alice",AgentActor.Role.SUPERVISOR);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",true));
        var collector=new AgentCardCollector(json);
        observe(collector,"list_device_alerts",Map.of(),ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"list_device_alerts\",\"data\":{\"items\":[{\"alertId\":\"7\",\"alertCode\":\"ALERT-CODE\",\"runtimeSnapshot\":\"PRIVATE\"}]}}"));
        observe(collector,"get_device_alert",Map.of(),ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"get_device_alert\",\"data\":{\"alertId\":\"8\"}}"));
        assertThat(collector.snapshot()).containsExactly(new AgentCards.Reference("DEVICE_ALERTS","list_device_alerts",List.of("7"),null),new AgentCards.Reference("DEVICE_ALERTS","get_device_alert",List.of("8"),null));
        assertThat(collector.snapshot().toString()).doesNotContain("ALERT-CODE","PRIVATE");
        var view=new ResourceAgentReadApi.AlertView("7","ALERT-CODE",null,"LINE-A","CAPTURE_EXCEPTION","MAJOR","RESOLVED",null,null);
        when(resources.alert(boss,7)).thenReturn(view);
        when(resources.alert(boss,8)).thenThrow(new com.ruanzhu.doorhandle.common.BusinessException(404,"private-alert"));
        var result=service.resolve(boss,collector.snapshot());assertThat(result.get(0).items()).isEqualTo(List.of(view));
        assertThat(result.get(1).status()).isEqualTo("PARTIAL");assertThat(result.get(1).items()).isEmpty();assertThat(result.toString()).doesNotContain("private-alert");
        clearInvocations(resources);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        assertThat(service.resolve(boss,collector.snapshot())).allMatch(v->v.status().equals("UNAVAILABLE")&&v.items().isEmpty());
        verifyNoInteractions(resources);
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
    @Test void modelOperationsCardsPersistOnlyIdsAndRecheckCurrentRoleAndRecord() throws Exception {
        var service=service();var boss=new AgentActor(1,"alice",AgentActor.Role.SUPERVISOR);
        when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",true));
        var collector=new AgentCardCollector(json);
        observe(collector,"get_model_operations",Map.of(),ToolResultBlock.text("{\"status\":\"OK\",\"source\":\"get_model_operations\",\"data\":{\"model\":{\"modelId\":7},\"evaluation\":{\"precisionScore\":0.9},\"private\":\"PRIVATE_TEXT\"}}"));
        var ref=new AgentCards.Reference("MODEL_OPERATIONS","get_model_operations",List.of("7"),null);
        assertThat(collector.snapshot()).containsExactly(ref);assertThat(collector.snapshot().toString()).doesNotContain("PRIVATE_TEXT","precisionScore");
        assertThat(json.readValue(json.writeValueAsString(new AgentCards.Envelope(1,"查询完成","run-1",collector.snapshot())),AgentCards.Envelope.class).cards()).containsExactly(ref);
        var current=operationsFixture();when(models.operations(boss,7)).thenReturn(current);
        assertThat(service.resolve(boss,collector.snapshot()).get(0).items()).isEqualTo(List.of(current));
        when(models.operations(boss,7)).thenThrow(new com.ruanzhu.doorhandle.common.BusinessException(404,"PRIVATE_PATH"));
        var removed=service.resolve(boss,collector.snapshot()).get(0);assertThat(removed.items()).isEmpty();assertThat(removed.status()).isEqualTo("PARTIAL");assertThat(removed.toString()).doesNotContain("PRIVATE_PATH");
        clearInvocations(models);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        var revoked=service.resolve(boss,collector.snapshot()).get(0);assertThat(revoked.items()).isEmpty();assertThat(revoked.status()).isEqualTo("UNAVAILABLE");verifyNoInteractions(models);
        for(String id:List.of("0","01","2147483648"))assertThatThrownBy(()->new AgentCards.Reference("MODEL_OPERATIONS","get_model_operations",List.of(id),null)).isInstanceOf(IllegalArgumentException.class);
    }
    private ModelAgentReadApi.Operations operationsFixture(){
        return new ModelAgentReadApi.Operations(new ModelAgentReadApi.ModelView(7,"六类检测","v2","PUBLISHED",true),"PASSED","ROLLOUT",
                new ModelAgentReadApi.Evaluation("登记测试集",java.math.BigDecimal.ZERO,null,null,null,0),
                new ModelAgentReadApi.Rollout("CANARY",0,"B",null),new ModelAgentReadApi.Usage(0,null,null),java.time.LocalDateTime.now(),List.of());
    }
    @Test void metricsHaveWhitelistedCountsAndNoInventedDefectRate(){
        var service=service();when(detection.metrics(actor,7)).thenReturn(new DetectionAgentReadApi.Metrics(Map.of("taskCount",2,"imageCount",9,"defectCount",12,"secret","private","defectRate",1.33),null,null,"OWNED_OR_ASSIGNED"));
        var view=service.resolve(actor,List.of(new AgentCards.Reference("METRICS","get_my_work_metrics",List.of(),7))).get(0);
        assertThat(view.metrics()).containsOnlyKeys("taskCount","imageCount","defectCount");assertThat(view.message()).contains("不等于");
    }
    @Test void realHarnessCollectsDeviceAndDetectionModelCardsThroughTheirSpecialistTools() throws Exception {
        var boss=new AgentActor(1,"alice",AgentActor.Role.SUPERVISOR);
        when(resources.devices(boss,1,20)).thenReturn(List.of(new ResourceAgentReadApi.DeviceView("9","CODE-OTHER","IDLE","ONLINE","CONNECTED","CONNECTED","STOPPED")));
        when(models.models(boss,1,20)).thenReturn(List.of(new ModelAgentReadApi.ModelView(7,"六类检测","v2","PUBLISHED",true)));
        when(resources.alerts(eq(boss),any())).thenReturn(new ResourceAgentReadApi.AlertPage(List.of(new ResourceAgentReadApi.AlertView("8","ALERT-code","9","CODE-OTHER","CAPTURE_EXCEPTION","MAJOR","OPEN",null,null)),null,false,java.time.LocalDateTime.now()));
        when(models.operations(boss,7)).thenReturn(operationsFixture());
        for(var setup:List.of(List.of("delegate_resource_management","list_devices","DEVICES","9"),List.of("delegate_model_ops","list_models","MODELS","7"),List.of("delegate_resource_management","list_device_alerts","DEVICE_ALERTS","8"),List.of("delegate_model_ops","get_model_operations","MODEL_OPERATIONS","7"))){
            var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-resource-card-fixture");var steps=new AtomicInteger();
            when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{int step=steps.getAndIncrement();ContentBlock block;
                if(step==0)block=ToolUseBlock.builder().id("delegate-call").name(setup.get(0)).input(Map.of("question","查询资源")).content("{\"question\":\"查询资源\"}").build();
                else if(step==1){Map<String,Object> args=setup.get(1).equals("get_model_operations")?Map.of("modelId","7"):Map.of();block=ToolUseBlock.builder().id("resource-call").name(setup.get(1)).input(args).content(json.writeValueAsString(args)).build();}
                else block=TextBlock.builder().text("模型虚构资源 ID 999 不会形成卡片").build();
                return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());});
            var toolkit=new BusinessToolkitFactory(detection,resources,models,json);
            var settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());
            var factory=new RoleAgentFactory(settings,toolkit,id->model);
            var conversation=new AgentScopeConversationService(factory,new AgentRunRegistry(),settings);
            var run=conversation.start(boss,"fixture-"+setup.get(2),List.of(new AgentConversationApi.Message("user","查询资源")),"",event->{});
            assertThat(run.result().get(15,java.util.concurrent.TimeUnit.SECONDS)).contains("999");
            assertThat(run.cards().get()).containsExactly(new AgentCards.Reference(setup.get(2),setup.get(1),List.of(setup.get(3)),null));
            assertThat(steps.get()).isEqualTo(4);
        }
        verify(resources).devices(boss,1,20);verify(models).models(boss,1,20);
        verify(resources).alerts(boss,new ResourceAgentReadApi.AlertQuery(null,null,null,null,20));
        verify(models).operations(boss,7);
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
