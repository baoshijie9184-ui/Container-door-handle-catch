package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.action.AgentActionService;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.*;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.tool.ToolCallParam;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import java.sql.Connection;
import java.time.*;
import java.util.*;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicInteger;
import static org.mockito.Mockito.*;

/** 只使用合成业务门面和隔离 H2；SDK、工具参数校验与确认事务调用生产实现。 */
final class AgentEvalFixture implements AutoCloseable {
    static final String VERSION="synthetic-business-h2-v2";
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules().disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    final AgentActor boss=new AgentActor(1,"eval.boss",AgentActor.Role.SUPERVISOR);
    final AgentActor other=new AgentActor(2,"eval.other",AgentActor.Role.SUPERVISOR);
    final AgentActor employee=new AgentActor(3,"eval.alice",AgentActor.Role.INSPECTOR);
    final JdbcTemplate jdbc;
    final Connection connection;
    final AgentActionService actions;
    final BusinessToolkitFactory toolkits;
    final AtomicInteger facadeCalls=new AtomicInteger(),modelCalls=new AtomicInteger();
    final List<String> tools=new ArrayList<>(),events=new ArrayList<>();
    String boundUser="",scope="",actionStatus="NONE";
    boolean error,secretMarkerLeaked,registeredWriteTool,failRead;
    JsonNode facts=json.createObjectNode();

    AgentEvalFixture() throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:eval_"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE","sa","");
        connection=source.getConnection();jdbc=new JdbcTemplate(source);
        try(var stream=getClass().getResourceAsStream("/db/migration-V19-agent-confirmation.sql")) {
            if(stream==null)throw new IllegalStateException("缺少确认迁移");
            var ddl=new String(stream.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8)
                    .replace(" COLLATE utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","").replace(" JSON"," VARCHAR(8192)");
            for(var sql:ddl.split(";"))if(!sql.isBlank())jdbc.execute(sql);
        }
        jdbc.execute("CREATE TABLE agent_run(run_id VARCHAR(128) PRIMARY KEY,user_id BIGINT,session_id VARCHAR(128),status VARCHAR(24))");
        jdbc.update("INSERT INTO agent_run VALUES('eval-run',1,'eval-session','COMPLETED')");
        jdbc.execute("CREATE TABLE fixture_task(id VARCHAR(128) PRIMARY KEY,writes INT NOT NULL,resource_version VARCHAR(64))");
        jdbc.update("INSERT INTO fixture_task VALUES('eval-task',0,'revision-1')");
        var assignments=mock(DetectionAssignmentApi.class);
        when(assignments.preview(any(),any())).thenAnswer(inv->{
            AgentActor actor=inv.getArgument(0);actor.requireSupervisor();
            return new DetectionAssignmentApi.Preview(inv.getArgument(1),new DetectionAssignmentApi.Values(null,null,null,null,"DETECTED"),
                    jdbc.queryForObject("SELECT resource_version FROM fixture_task",String.class));
        });
        when(assignments.apply(any(),any(),anyString())).thenAnswer(inv->{
            AgentActor actor=inv.getArgument(0);actor.requireSupervisor();facadeCalls.incrementAndGet();boundUser=actor.username();
            DetectionAssignmentApi.Command command=inv.getArgument(1);
            jdbc.update("UPDATE fixture_task SET writes=writes+1 WHERE id='eval-task'");
            return new DetectionAssignmentApi.Applied("eval-task",new DetectionAssignmentApi.Values(command.qualityStation(),command.assignee(),null,command.assignmentRemark(),"REVIEWING"));
        });
        var journal=mock(AgentJournal.class);when(journal.enabled()).thenReturn(true);
        var settings=new AgentActionProperties();settings.setEnabled(true);
        actions=new AgentActionService(jdbc,new DataSourceTransactionManager(source),json,journal,assignments,settings);actions.verifySchema();
        var detection=mock(DetectionAgentReadApi.class);
        when(detection.tasks(any(),anyInt(),anyInt(),anyBoolean())).thenAnswer(inv->{
            AgentActor actor=inv.getArgument(0);read(actor);
            var records=new ArrayList<DetectionAgentReadApi.TaskView>();records.add(task("fixture-own"));records.add(task("fixture-assigned"));
            if(actor.supervisor())for(int index=3;index<=5;index++)records.add(task("fixture-enterprise-"+index));
            return new DetectionAgentReadApi.TaskPage(records,records.size(),inv.getArgument(1),inv.getArgument(2));
        });
        when(detection.task(any(),anyString())).thenAnswer(inv->{AgentActor actor=inv.getArgument(0);read(actor);return task(inv.getArgument(1));});
        when(detection.metrics(any(),anyInt())).thenAnswer(inv->{
            AgentActor actor=inv.getArgument(0);read(actor);int days=inv.getArgument(1);
            var to=LocalDateTime.of(2026,10,13,12,0);
            return new DetectionAgentReadApi.Metrics(Map.of("taskCount",actor.supervisor()?5:2,"imageCount",180,"defectCount",23),to.minusDays(days),to,scope);
        });
        var reports=mock(com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway.class);when(reports.draftsEnabled()).thenReturn(true);
        when(reports.list(any(),anyInt(),anyInt(),any(),any())).thenAnswer(inv->{AgentActor actor=inv.getArgument(0);read(actor);return new QualityReportAgentApi.Page(List.of(new QualityReportAgentApi.Summary("qr-11111111-1111-1111-1111-111111111111","eval-task","合成报告","SUBMITTED",2,actor.username())),1,inv.getArgument(1),inv.getArgument(2));});
        when(reports.get(any(),anyString())).thenAnswer(inv->{AgentActor actor=inv.getArgument(0);read(actor);return reportDetail(actor,inv.getArgument(1));});
        when(reports.write(any(),anyString(),anyString(),anyString(),anyMap())).thenAnswer(inv->{AgentActor actor=inv.getArgument(0);read(actor);jdbc.update("UPDATE fixture_task SET writes=writes+1");return reportDetail(actor,"qr-11111111-1111-1111-1111-111111111111");});
        toolkits=new BusinessToolkitFactory(detection,mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json,actions,reports);
    }
    private QualityReportAgentApi.Detail reportDetail(AgentActor actor,String id){return new QualityReportAgentApi.Detail(new QualityReportAgentApi.Summary(id,"eval-task","合成报告","DRAFT",1,actor.username()),"合成意见",Map.of("totalImages",90),null,null,"/quality/reports?reportId="+id);}
    private DetectionAgentReadApi.TaskView task(String id) {
        return new DetectionAgentReadApi.TaskView(id,"COMPLETED","DETECTED","fixture-camera",90,90,12,"PENDING",null,LocalDateTime.of(2026,10,12,9,0));
    }
    private void read(AgentActor actor) {
        facadeCalls.incrementAndGet();boundUser=actor.username();scope=actor.supervisor()?"SINGLE_ENTERPRISE":"OWNED_OR_ASSIGNED";
        if(failRead)throw new IllegalStateException("eval-secret-marker-do-not-export");
    }
    AgentActor actor(String name) {
        return switch(name){case "employee-a"->employee;case "supervisor-a"->boss;case "supervisor-b"->other;default->throw new IllegalArgumentException("未知合成身份");};
    }
    String execute(AgentEvalDataset.Case spec,Path workspace) throws Exception {
        AgentActor actor=actor(spec.actorFixture());JsonNode params=spec.parameters();
        return switch(spec.scenario()) {
            case "READ_TOOL" -> {
                failRead=params.path("failRead").asBoolean(false);
                var definition=definition(actor,params.path("specialist").asText());
                var toolkit=toolkits.create(actor,definition,"eval-run");
                String name=params.path("tool").asText();var tool=toolkit.getTool(name);
                if(tool==null)throw new IllegalArgumentException("未登记的评测工具");
                tools.add(name);
                var input=json.convertValue(params.path("arguments"),Map.class);
                var result=tool.callAsync(ToolCallParam.builder().input(input).build()).block(Duration.ofSeconds(5));
                readResult(result);
                yield error?"TOOL_ERROR":"OK";
            }
            case "REGISTER_DENIED" -> {
                try {toolkits.create(actor,definition(boss,"detection-quality"),"eval-run");yield "OK";}
                catch(SecurityException expected){yield "DENIED";}
            }
            case "STAFF_WRITE_ABSENT" -> {
                registeredWriteTool=RoleAgentCatalog.specialists(actor,true).stream().anyMatch(def->toolkits.create(actor,def,"eval-run").getToolNames().contains(AgentActionService.TOOL));
                yield "OK";
            }
            case "SDK_DELEGATION" -> {sdk(spec,actor,workspace);yield error?"TOOL_ERROR":"OK";}
            case "REPORT_APPROVAL_ABSENT" -> {
                var names=toolkits.create(actor,definition(actor,"report-assistant"),"eval-run").getToolNames();
                facts=json.createObjectNode().put("approvalToolRegistered",names.stream().anyMatch(name->name.contains("approve")||name.contains("submit")||name.contains("export")));
                yield "OK";
            }
            case "ACTION" -> action(spec,actor);
            default -> throw new IllegalArgumentException("未知评测场景");
        };
    }
    private RoleAgentCatalog.Definition definition(AgentActor actor,String id) {
        return RoleAgentCatalog.specialists(actor,true,true,true).stream().filter(def->def.id().equals(id)).findFirst().orElseThrow(()->new IllegalArgumentException("未知评测专业 Agent"));
    }
    private void readResult(ToolResultBlock result) throws Exception {
        if(result==null)throw new IllegalStateException("工具没有返回结果");
        error=result.getState()==ToolResultState.ERROR;
        String output=result.getOutput().stream().filter(TextBlock.class::isInstance).map(TextBlock.class::cast).map(TextBlock::getText).reduce("",String::concat);
        secretMarkerLeaked=output.contains("eval-secret-marker-do-not-export");
        if(!error)facts=json.readTree(output);
    }
    private void sdk(AgentEvalDataset.Case spec,AgentActor actor,Path workspace) {
        var params=spec.parameters();String specialist=params.path("specialist").asText();String tool=params.path("tool").asText();
        var arguments=json.convertValue(params.path("arguments"),Map.class);
        var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-eval-model");
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
            int step=modelCalls.getAndIncrement();ContentBlock block;
            if(step==0)block=ToolUseBlock.builder().id("eval-delegate-call").name("delegate_"+specialist.replace('-','_'))
                    .input(Map.of("question",spec.input())).content(json.writeValueAsString(Map.of("question",spec.input()))).build();
            else if(step==1)block=ToolUseBlock.builder().id("eval-business-call").name(tool).input(arguments).content(json.writeValueAsString(arguments)).build();
            else block=TextBlock.builder().text("合成评测回复；不作为模型质量评分依据").build();
            return reactor.core.publisher.Flux.just(ChatResponse.builder().id("eval-response-"+step).content(List.of(block)).build());
        });
        var run=mock(AgentJournal.Run.class);when(run.id()).thenReturn("eval-run");
        doAnswer(inv->{
            String type=inv.getArgument(0);Map<String,Object> payload=inv.getArgument(1);events.add(type);
            if(type.equals("TOOL_STARTED"))tools.add(payload.get("tool").toString());
            if(type.equals("TOOL_ERROR"))error=true;
            if(payload.containsKey("scope"))scope=payload.get("scope").toString();
            return null;
        }).when(run).event(anyString(),anyMap());
        var settings=new AgentScopeProperties();settings.setWorkspace(workspace.toString());
        var factory=new RoleAgentFactory(settings,toolkits,id->model);
        try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(actor,null,new AgentJournalMiddleware(run,actor,true,true,true))) {
            agent.call(spec.input()).block(Duration.ofSeconds(10));
        }
        var pending=actions.list(actor,null,null,10);
        if(!pending.isEmpty())actionStatus=pending.get(0).status();
    }
    private String action(AgentEvalDataset.Case spec,AgentActor actor) {
        var command=new DetectionAssignmentApi.Command("eval-task","fixture-station","eval.alice",null,"fixture-only");
        var draft=actions.propose(boss,"eval-run","eval-call",command);actionStatus=draft.status();
        String decision=spec.decision();
        switch(decision) {
            case "EXPIRE"->jdbc.update("UPDATE agent_pending_action SET expires_at=DATEADD('MINUTE',-1,CURRENT_TIMESTAMP)");
            case "RESOURCE_CHANGE"->jdbc.update("UPDATE fixture_task SET resource_version='revision-2'");
            case "RUN_CANCELLED"->jdbc.update("UPDATE agent_run SET status='CANCELLED'");
            case "AUDIT_FAILURE"->jdbc.execute("ALTER TABLE agent_action_audit ADD CONSTRAINT fail_eval_audit CHECK(event_type<>'TOOL_EXECUTION_COMPLETED')");
            default->{ }
        }
        String outcome="OK";
        try {
            if(decision.equals("ROLE_REVOKED"))actor=new AgentActor(boss.userId(),boss.username(),AgentActor.Role.INSPECTOR);
            if(!decision.equals("NONE"))actions.decide(actor,draft.actionId(),1,Set.of("EXPIRE","RESOURCE_CHANGE","RUN_CANCELLED","AUDIT_FAILURE","REPEAT_APPROVE","ROLE_REVOKED").contains(decision)?"APPROVE":decision);
            if(decision.equals("REPEAT_APPROVE"))actions.decide(actor,draft.actionId(),1,"APPROVE");
        } catch(org.springframework.web.server.ResponseStatusException denied) {
            if(denied.getStatusCode().value()!=404)throw denied;
            outcome="DENIED";
        } catch(org.springframework.dao.DataAccessException failed) {
            if(!decision.equals("AUDIT_FAILURE"))throw failed;
            outcome="ROLLED_BACK";
        }
        actionStatus=actions.get(boss,draft.actionId()).status();
        events.addAll(actions.audit(boss,draft.actionId()).stream().map(AgentActionService.Audit::eventType).toList());
        facts=json.createObjectNode().put("auditBusinessChanges",jdbc.queryForObject("SELECT COUNT(*) FROM agent_action_audit WHERE event_type='BUSINESS_CHANGED'",Integer.class));
        return outcome;
    }
    ObjectNode observation(String outcome) {
        var observed=json.createObjectNode();observed.put("outcome",outcome);
        observed.set("tools",json.valueToTree(tools));observed.set("auditEvents",json.valueToTree(events));observed.set("facts",facts);
        observed.put("facadeCalls",facadeCalls.get());observed.put("businessWrites",jdbc.queryForObject("SELECT writes FROM fixture_task",Integer.class));
        observed.put("pendingCount",jdbc.queryForObject("SELECT COUNT(*) FROM agent_pending_action",Integer.class));
        observed.put("actionStatus",actionStatus);observed.put("toolError",error);observed.put("modelCalls",modelCalls.get());
        observed.put("boundUser",boundUser);observed.put("scope",scope);observed.put("writeToolRegistered",registeredWriteTool);
        observed.put("secretMarkerLeaked",secretMarkerLeaked);
        // 测试模型未提供供应商用量，必须显示未知，不能按零 token 或零价格宣称成本。
        observed.putNull("inputTokens");observed.putNull("outputTokens");observed.putNull("cost");
        return observed;
    }
    @Override public void close() throws Exception {connection.close();}
}
