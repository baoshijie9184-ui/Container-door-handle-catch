package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournal;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.tool.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import reactor.core.publisher.*;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.mockito.Mockito.*;

/** Separate JVM deliberately exits without close/finally to exercise real crash durability. */
public final class WorkbenchCrashProbe {
    public static void main(String[] args)throws Exception{
        var config=new ObjectMapper().readTree(Path.of("../work/workbench-mysql/connection.json").toFile());String database=config.path("database").asText();
        if(!database.matches("doorhandle_wb_verify_[a-f0-9]{10}")||!config.path("url").asText().startsWith("jdbc:mysql://127.0.0.1:13308/"+database+"?"))throw new SecurityException("Only isolated verification database is allowed");
        var source=new com.zaxxer.hikari.HikariDataSource();source.setJdbcUrl(config.path("url").asText()+"&connectTimeout=8000&socketTimeout=15000");source.setUsername(config.path("username").asText());source.setPassword(config.path("password").asText());source.setConnectionInitSql("SET time_zone = '+08:00'");source.setMaximumPoolSize(3);source.setMinimumIdle(1);var jdbc=new JdbcTemplate(source);var store=new WorkbenchStore(jdbc,new DataSourceTransactionManager(source),new ObjectMapper());
        var actor=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);var users=mock(BusinessUserDirectory.class);when(users.current(1,"alice")).thenReturn(new BusinessUserDirectory.Identity(1,"alice",false));
        var provider=mock(ObjectProvider.class);when(provider.getObject()).thenReturn(mock(WorkbenchSessionApi.class));var settings=new WorkbenchProperties();settings.setEnabled(true);var journal=mock(AgentJournal.class);when(journal.enabled()).thenReturn(true);
        String scenario=args[0];var calls=new AtomicInteger();var model=mock(Model.class);when(model.getModelName()).thenReturn("crash-script");when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
            int turn=calls.getAndIncrement();if(scenario.equals("before-model"))Runtime.getRuntime().halt(25);if(scenario.equals("child")&&turn>0){var rows=jdbc.queryForList("SELECT kind,status FROM agent_workbench_item WHERE kind IN ('EXECUTION','CHILD')");boolean parentWaiting=rows.stream().anyMatch(row->"EXECUTION".equals(row.get("kind"))&&"WAITING_CHILD".equals(row.get("status")));boolean childRunning=rows.stream().anyMatch(row->"CHILD".equals(row.get("kind"))&&"RUNNING".equals(row.get("status")));System.out.println("CHILD_CUT_REACHED parentWaiting="+parentWaiting+" childRunning="+childRunning);Runtime.getRuntime().halt(parentWaiting&&childRunning?28:29);}if(turn>0)Runtime.getRuntime().halt(24);
            var tool=scenario.equals("waiting")?call("durable-question","ask_user_question",Map.of("text","哪个批次","questionType","TEXT")):scenario.equals("child")?call("durable-child","start_background_task",Map.of("specialist","detection-task","question","子任务中断演练")):call("durable-effect","write_effect",Map.of());
            return Flux.just(ChatResponse.builder().content(List.of(tool)).finishReason("tool_calls").build());});
        var roles=mock(RoleAgentFactory.class);if(scenario.equals("child")){var toolkits=mock(BusinessToolkitFactory.class);when(toolkits.create(any(),any(),anyString())).thenAnswer(inv->new Toolkit());roles=new RoleAgentFactory(new AgentScopeProperties(),toolkits,id->model);var recorded=mock(AgentJournal.Run.class);when(recorded.id()).thenReturn("crashed-child-run");when(journal.beginChild(any(),anyString(),anyString(),anyString(),anyString())).thenReturn(recorded);}
        var service=new AgentWorkbenchService(store,settings,users,provider,roles,journal);var scope=service.prepare(actor,"s1","查看任务","crashed-attempt");
        var toolkit=new Toolkit();toolkit.registerAgentTool(new AgentTool(){public String getName(){return "write_effect";}public String getDescription(){return "write test effect";}public Map<String,Object>getParameters(){return Map.of("type","object","properties",Map.of());}public Mono<ToolResultBlock>callAsync(ToolCallParam param){return Mono.fromCallable(()->{if(scenario.equals("before-effect"))Runtime.getRuntime().halt(26);jdbc.update("INSERT INTO agent_workbench_crash_effect(id) VALUES(1)");if(scenario.equals("unknown"))Runtime.getRuntime().halt(23);return ToolResultBlock.text("effect committed");});}});scope.install(toolkit);
        var agent=ReActAgent.builder().name("employee-main").model(model).toolkit(toolkit).middlewares(List.of(scope)).stateStore(scope.stateStore()).defaultSessionId(scope.sdkSession()).enablePendingToolRecovery(false).enableMetaTool(false).enableTaskList(false).build();
        try{agent.call(List.of(new UserMessage("查看任务")),RuntimeContext.builder().userId("1").sessionId(scope.sdkSession()).build()).block();}catch(AgentWorkbenchService.Yield waiting){if(scenario.equals("waiting"))Runtime.getRuntime().halt(27);if(scenario.equals("child")){agent.close();scope.release();service.dispatch();Thread.sleep(30000);}else throw waiting;}throw new IllegalStateException("Crash point was not reached");
    }
    private static ToolUseBlock call(String id,String name,Map<String,Object> input)throws Exception{return ToolUseBlock.builder().id(id).name(name).input(input).content(new ObjectMapper().writeValueAsString(input)).build();}
}
