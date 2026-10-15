package com.ruanzhu.doorhandle.module.ai.report;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.tool.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Path;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ReportToolsTest {
    @TempDir Path workspace;
    final AgentActor employee=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    final AgentReportGateway reports=mock(AgentReportGateway.class);
    final ObjectMapper json=new ObjectMapper();
    final String reportId="qr-12345678-1234-1234-1234-123456789012";
    QualityReportAgentApi.Detail detail(){return new QualityReportAgentApi.Detail(new QualityReportAgentApi.Summary(reportId,"task-1","报告","DRAFT",1,"alice"),"草稿",Map.of("totalImages",4),null,null,"/quality/reports?reportId="+reportId);}
    ToolResultBlock call(String tool,Map<String,Object> input){return new ReportTools(tool,employee,"run-1",reports,json).callAsync(ToolCallParam.builder().input(input).toolUseBlock(ToolUseBlock.builder().id("report-call").name(tool).input(input).build()).build()).block(Duration.ofSeconds(5));}
    String text(ToolResultBlock r){return r.getOutput().stream().filter(TextBlock.class::isInstance).map(TextBlock.class::cast).map(TextBlock::getText).reduce("",String::concat);}
    @Test void writesUseBoundActorRunAndCallButNeverAcceptIdentityOrConfirmationParameters(){
        var args=Map.<String,Object>of("taskId","task-1","title","报告","narrative","草稿");when(reports.write(employee,"run-1","report-call","create_report_draft",args)).thenReturn(detail());
        assertThat(text(call("create_report_draft",args))).contains("PRIVATE_DRAFT_SAVED","尚未提交审批","DRAFT");
        verify(reports).write(employee,"run-1","report-call","create_report_draft",args);
        for(String key:List.of("userId","role","runId","requestId","confirmationToken","status")){
            var spoof=new HashMap<>(args);spoof.put(key,"forged");assertThat(text(call("create_report_draft",spoof))).contains("参数不合法");
        }
        verifyNoMoreInteractions(reports);
    }
    @Test void missingBlankOversizedAndFractionalInputsFailBeforeGateway(){
        for(var args:List.of(Map.<String,Object>of(),Map.<String,Object>of("taskId","../bad","title","标题","narrative","意见"),
                Map.<String,Object>of("taskId","task-1","title"," ","narrative","意见"),Map.<String,Object>of("taskId","task-1","title","标题","narrative","x".repeat(10001))))
            assertThat(text(call("create_report_draft",args))).contains("参数不合法");
        assertThat(text(call("edit_report_draft",Map.of("reportId",reportId,"expectedVersion",1.2,"title","标题","narrative","意见")))).contains("参数不合法");
        assertThat(text(call("list_quality_reports",Map.of("status","PUBLISHED")))).contains("参数不合法");verifyNoInteractions(reports);
    }
    @Test void toolFailuresRedactDatabaseAndSecretDetails(){
        when(reports.get(employee,reportId)).thenThrow(new IllegalStateException("password sk-private jdbc:mysql:/secret"));
        assertThat(text(call("get_quality_report",Map.of("reportId",reportId)))).doesNotContain("sk-private","jdbc:mysql","password").contains("未执行审批");
    }
    @Test void queryCatalogIncludesReadToolsButWritesRequireJournalAndApprovalsAreNeverRegistered(){
        when(reports.draftsEnabled()).thenReturn(false);
        var factory=new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json,null,reports);
        var definitions=RoleAgentCatalog.specialists(employee,false,true,false);assertThat(definitions).hasSize(5);
        var report=definitions.get(4);assertThat(report.tools()).containsExactly("list_quality_reports","get_quality_report");
        assertThatThrownBy(()->factory.create(employee,RoleAgentCatalog.specialists(employee,false,true,true).get(4),"run-1")).isInstanceOf(SecurityException.class);
        when(reports.draftsEnabled()).thenReturn(true);
        var tools=factory.create(employee,RoleAgentCatalog.specialists(employee,false,true,true).get(4),"run-1");
        assertThat(tools.getToolNames()).containsExactlyInAnyOrder("list_quality_reports","get_quality_report","create_report_draft","edit_report_draft");
        assertThat(tools.getTool("create_report_draft").isReadOnly()).isFalse();assertThat(tools.getTool("get_quality_report").isReadOnly()).isTrue();
    }
    @Test void realHarnessDelegatesReportDraftAndRecordsActualPolicyWithoutApproving(){
        when(reports.draftsEnabled()).thenReturn(true);when(reports.write(eq(employee),eq("run-1"),eq("draft-call"),eq("create_report_draft"),anyMap())).thenReturn(detail());
        var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-report-test");var steps=new AtomicInteger();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
            int step=steps.getAndIncrement();ContentBlock block;
            if(step==0)block=ToolUseBlock.builder().id("delegate-report").name("delegate_report_assistant").input(Map.of("question","保存本人报告草稿")).content("{\"question\":\"保存本人报告草稿\"}").build();
            else if(step==1)block=ToolUseBlock.builder().id("draft-call").name("create_report_draft").input(Map.of("taskId","task-1","title","报告","narrative","草稿")).content("{\"taskId\":\"task-1\",\"title\":\"报告\",\"narrative\":\"草稿\"}").build();
            else block=TextBlock.builder().text("个人草稿已保存，尚未提交审批").build();
            return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());
        });
        var factory=new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json,null,reports);
        var settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());var agents=new RoleAgentFactory(settings,factory,id->model);
        var run=mock(AgentJournal.Run.class);when(run.id()).thenReturn("run-1");
        var cards=new com.ruanzhu.doorhandle.module.ai.card.AgentCardCollector(json);
        try(var agent=(io.agentscope.harness.agent.HarnessAgent)agents.create(employee,null,new AgentJournalMiddleware(run,employee,false,true,true),cards)){
            assertThat(agent.getToolkit().getTool("delegate_report_assistant").isReadOnly()).isFalse();
            assertThat(agent.call("为 task-1 保存本人报告草稿").block(Duration.ofSeconds(10)).getTextContent()).contains("尚未提交审批");
        }
        verify(reports).write(eq(employee),eq("run-1"),eq("draft-call"),eq("create_report_draft"),anyMap());
        verify(run).event(eq("AUTHORIZATION_ALLOWED"),argThat(p->"create_report_draft".equals(p.get("tool"))&&AgentReportGateway.POLICY.equals(p.get("policyVersion"))&&"delegate-report".equals(p.get("parentCallId"))));
        assertThat(steps.get()).isEqualTo(4);
        assertThat(cards.snapshot()).containsExactly(new AgentCards.Reference("REPORTS","create_report_draft",List.of(reportId),null));
    }
}
