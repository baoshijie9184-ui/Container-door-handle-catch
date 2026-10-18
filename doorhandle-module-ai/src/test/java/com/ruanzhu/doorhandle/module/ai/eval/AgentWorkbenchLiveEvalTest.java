package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.model.AgentModelService;
import io.agentscope.core.message.Msg;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import reactor.core.publisher.Flux;
import java.nio.file.*;
import java.security.MessageDigest;
import java.time.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

/** Opt-in paid execution with real SDK/JDBC orchestration and synthetic account/business facades. */
@EnabledIfSystemProperty(named="agent.workbench.live",matches="true")
class AgentWorkbenchLiveEvalTest {
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    @Test @Timeout(900)
    void plansYieldAndProfessionalsContinueWithIsolatedDurableHistory() throws Exception {
        Path project=Path.of(System.getProperty("agent.routing.project")).toRealPath();
        Path output=Path.of(System.getProperty("agent.routing.output")).toAbsolutePath().normalize();
        if(!output.startsWith(project.resolve("work"))||Files.exists(output))throw new IllegalArgumentException("Use a new project-owned experiment directory");
        String provider=System.getProperty("agent.routing.provider","deepseek");
        var connection=LiveProviderConfig.load(project,provider);
        String modelId=provider+":"+(provider.equals("deepseek")?connection.getDeepseek().getModel():connection.getDashscope().getModel());
        var requests=new AtomicInteger();var sdkSettings=new AgentScopeProperties();sdkSettings.setModel(modelId);
        var models=new AgentModelService(connection,sdkSettings);
        Model actual=models.resolve(modelId);
        Model bounded=new Model(){
            public String getModelName(){return actual.getModelName();}
            public int getContextWindowSize(){return actual.getContextWindowSize();}
            public Flux<ChatResponse> stream(List<Msg> messages,List<ToolSchema> tools,GenerateOptions options){
                return Flux.defer(()->{
                    if(requests.incrementAndGet()>28)return Flux.error(new IllegalStateException("Workbench evaluation request budget exhausted"));
                    return actual.stream(messages,tools,options);
                });
            }
        };
        Files.createDirectories(output);
        var report=new LinkedHashMap<String,Object>();var checks=new ArrayList<String>();var results=new ArrayList<Map<String,Object>>();
        report.put("at",OffsetDateTime.now(ZoneOffset.ofHours(8)).toString());report.put("modelId",modelId);
        report.put("mode","REAL_PROVIDER_SYNTHETIC_BUSINESS");report.put("sdkVersion","2.0.4");
        report.put("httpMaxAttempts",1);report.put("fallbackEnabled",false);report.put("maxModelRequests",28);
        report.put("gitCommit",System.getProperty("agent.routing.commit","UNKNOWN"));report.put("workingTreeDirty",System.getProperty("agent.routing.dirty","UNKNOWN"));
        var hashes=new TreeMap<String,String>();
        for(String path:List.of("workbench/AgentWorkbenchService.java","workbench/JdbcWorkbenchStateStore.java","service/AgentScopeConversationService.java","agent/RoleAgentFactory.java","agent/RoleAgentCatalog.java","journal/AgentJournalMiddleware.java","model/AgentModelService.java","model/ManagedAgentModel.java"))
            hashes.put(path,hash(project.resolve("doorhandle-module-ai/src/main/java/com/ruanzhu/doorhandle/module/ai/"+path)));
        for(String name:List.of("AgentWorkbenchLiveEvalTest.java","WorkbenchExecutionFixture.java","LiveProviderConfig.java"))
            hashes.put(name,hash(project.resolve("doorhandle-module-ai/src/test/java/com/ruanzhu/doorhandle/module/ai/eval/"+name)));
        report.put("sourceHashes",hashes);report.put("checks",checks);report.put("results",results);
        report.put("gatePassed",false);report.put("productionReleaseApproved",false);report.put("price",null);
        write(output,report);
        String mysql=System.getProperty("agent.workbench.mysqlConfig","");
        try(var f=new WorkbenchExecutionFixture(project,output.resolve("workspace"),modelId,id->bounded,mysql.isBlank()?null:Path.of(mysql))) {
            report.put("databaseKind",f.databaseKind);
            try {
                for(var actor:List.of(f.employee,f.supervisor)) {
                    String session="live-plan-"+actor.userId();
                    String question="/plan 只读查询任务 "+f.task(actor)+" 的检测状态、缺陷总数和当前质检复核状态。计划批准后使用且仅使用一个检测专业子任务获取一次详情并汇总，不查询历史列表，不修改业务。";
                    f.start(actor,session,UUID.randomUUID().toString(),question).result().get(100,TimeUnit.SECONDS);
                    f.waitFor(actor,session,"WAITING_PLAN",15);
                    assertThat(f.calls(actor)).isZero();
                    assertThat(f.item(actor,session,"PLAN").status()).isEqualTo("PENDING");
                    assertThat(f.workbench.list(actor,session)).noneMatch(item->item.kind().equals("CHILD"));
                    checks.add(actor.role()+":UNAPPROVED_PLAN_HAS_NO_BUSINESS_OR_CHILD_EXECUTION");
                    write(output,report);
                }
                var slots=(java.util.concurrent.Semaphore)org.springframework.test.util.ReflectionTestUtils.getField(f.workbench,"slots");
                assertThat(slots.availablePermits()).isEqualTo(2);checks.add("WAITING_PLANS_RELEASE_MODEL_SLOTS");
                assertThatThrownBy(()->f.workbench.list(f.supervisor,"live-plan-"+f.employee.userId())).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
                checks.add("CROSS_ACCOUNT_WORKBENCH_DENIED");
                // An explicit test-user action approves each current version; a model response is never approval.
                for(var actor:List.of(f.employee,f.supervisor))f.approve(actor,"live-plan-"+actor.userId());
                for(var actor:List.of(f.employee,f.supervisor)) {
                    String session="live-plan-"+actor.userId();f.waitFor(actor,session,"COMPLETED",200);
                    assertThat(f.calls(actor)).isEqualTo(1);
                    var children=f.workbench.list(actor,session).stream().filter(item->item.kind().equals("CHILD")).toList();assertThat(children).hasSize(1);
                    var child=children.get(0);assertThat(child.status()).isEqualTo("COMPLETED");
                    assertThat(child.data().get("specialist")).isEqualTo(actor.supervisor()?"detection-quality":"detection-task");
                    String reply=Objects.toString(f.item(actor,session,"EXECUTION").data().get("result"),"");
                    assertThat(reply).contains(f.task(actor));
                    assertThat(reply).containsPattern(actor.supervisor()?"(?<![0-9])13(?![0-9])":"(?<![0-9])7(?![0-9])");
                    assertThat(reply).containsPattern("(?i)COMPLETED|已完成|完成");assertThat(reply).containsPattern("(?i)PENDING|待.*复核|尚未.*复核|未.*审核");
                    assertThat(reply).doesNotContain(f.task(actor.supervisor()?f.employee:f.supervisor));
                    checks.add(actor.role()+":APPROVED_ASYNC_CHILD_RETURNED_OWN_FACTS_ONCE");
                    org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(15)).until(()->{
                        var rows=f.jdbc.queryForList("SELECT payload FROM agent_workbench_item WHERE item_id=?",child.id());
                        return Boolean.TRUE.equals(json.readTree(rows.get(0).get("payload").toString()).path("yieldReady").asBoolean());
                    });
                    var settled=f.item(actor,session,"CHILD");
                    f.workbench.command(actor,session,settled.id(),settled.revision(),UUID.randomUUID().toString(),"child-message",Map.of("content","仅根据你先前获取的详情，说明六类缺陷分别的数量是否已提供。不要调用任何工具或重新查询，未提供的明确说未知。"));
                    org.awaitility.Awaitility.await().pollInterval(Duration.ofMillis(250)).atMost(Duration.ofSeconds(100)).until(()->{f.workbench.dispatch();return f.item(actor,session,"CHILD").status().equals("COMPLETED");});
                    String followup=Objects.toString(f.item(actor,session,"CHILD").data().get("result"),"");
                    assertThat(followup).containsPattern("未知|未提供|没有提供|无法|不能确定");assertThat(f.calls(actor)).isEqualTo(1);
                    assertThat(f.journal.list(actor,"child-"+child.id(),null,10)).hasSize(2);
                    checks.add(actor.role()+":SPECIALIST_FOLLOWUP_REUSED_HISTORY_WITHOUT_BUSINESS_REPLAY");
                    var events=new ArrayList<>(f.events(actor,session));events.addAll(f.events(actor,"child-"+child.id()));
                    assertThat(events).anyMatch(event->event.type().equals("MODEL_ATTEMPT_COMPLETED"));
                    assertThat(events).noneMatch(event->Set.of("AUTHORIZATION_DENIED","MODEL_ATTEMPT_ERROR").contains(event.type()));
                    assertThat(events.stream().filter(event->event.type().equals("MODEL_ATTEMPT_STARTED"))).allMatch(event->modelId.equals(event.payload().get("modelId")));
                    results.add(Map.of("role",actor.role().name(),"reply",reply,"followup",followup,"items",f.workbench.list(actor,session),"events",events));
                    write(output,report);
                }
                assertThat(f.businessCalls).hasSize(2);
                assertThat(f.jdbc.queryForObject("SELECT COUNT(*) FROM agent_workbench_sdk_state",Integer.class)).isEqualTo(4);
                checks.add("FOUR_MAIN_AND_CHILD_SDK_STATE_SLOTS_PERSISTED");
                var usage=f.jdbc.queryForList("SELECT item_id,payload FROM agent_workbench_item WHERE kind='USAGE'");
                assertThat(usage).hasSize(requests.get());
                for(var row:usage){var data=json.readTree(row.get("payload").toString());assertThat(data.path("modelId").asText()).isEqualTo(modelId);assertThat(data.path("basis").asText()).isEqualTo("PROVIDER_REPORTED");assertThat(data.path("inputTokens").isNumber()).isTrue();assertThat(data.path("outputTokens").isNumber()).isTrue();}
                report.put("persistedUsage",usage);checks.add("USAGE_MATCHES_REAL_REQUEST_COUNT_AND_RETAINS_PROVIDER_VALUES");
                report.put("gatePassed",true);
            } finally {
                report.put("modelRequests",Math.min(requests.get(),28));report.put("budgetExceeded",requests.get()>28);
                report.put("businessCalls",f.businessCalls);
                report.put("lastPublicItems",f.owners.keySet().stream().sorted().map(session->f.workbench.list(f.owners.get(session)==f.employee.userId()?f.employee:f.supervisor,session)).toList());
                write(output,report);
            }
        }
    }
    String hash(Path path)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));}
    void write(Path output,Map<String,Object> report)throws Exception{
        Path temporary=output.resolve("report.tmp");json.writerWithDefaultPrettyPrinter().writeValue(temporary.toFile(),report);
        Files.move(temporary,output.resolve("report.json"),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
    }
}
