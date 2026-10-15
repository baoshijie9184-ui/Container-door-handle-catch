package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.RoleAgentFactory;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.mcp.*;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@EnabledIfSystemProperty(named="agent.local.mcp.mysql",matches="true")
class LocalMcpMysqlTest {
    @Test void installedPrivateFetchIsCalledThroughActualHarnessAndNativeStdioAndDisabledAfterward()throws Exception {
        Path root=Path.of(System.getProperty("agent.report.project","..")).toAbsolutePath();
        try(var context=new AnnotationConfigApplicationContext(Config.class)){
            var users=context.getBean(UserMapper.class);var json=context.getBean(ObjectMapper.class);var mcp=context.getBean(LocalMcpService.class);var journal=context.getBean(JdbcAgentJournal.class);
            var staff=users.findByUsername("inspector.demo");var other=users.findByUsername("supervisor.demo");var actor=new AgentActor(staff.getId(),staff.getUsername(),AgentActor.Role.INSPECTOR);var boss=new AgentActor(other.getId(),other.getUsername(),AgentActor.Role.SUPERVISOR);
            var state=mcp.view(actor);assertThat(state).containsEntry("status","INSTALLED");assertThat(mcp.available(boss)).isFalse();mcp.enabled(actor,((Number)state.get("revision")).intValue(),true);
            String suffix=UUID.randomUUID().toString().substring(0,8);var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-local-mcp");var steps=new AtomicInteger();var result=new AtomicReference<String>();
            var args=Map.<String,Object>of("url","https://example.com/","max_length",1200);
            when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{ContentBlock block;if(steps.getAndIncrement()==0)block=ToolUseBlock.builder().id("fetch-stdio-call").name(FetchMcpRuntime.TOOL).input(args).content(json.writeValueAsString(args)).build();else{result.set(json.writeValueAsString(inv.getArgument(0)));block=TextBlock.builder().text("已调用本地 MCP 获取公开网页").build();}return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());});
            var settings=new AgentScopeProperties();settings.setWorkspace(root.resolve(".agentscope/workspace").toString());var factory=new RoleAgentFactory(settings,new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json),id->model,null,mcp);
            var run=journal.begin(actor,"mcp-session-"+suffix,"employee-main","CHAT","mcp-load-"+suffix,"scripted-local-mcp");
            try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(actor,null,new AgentJournalMiddleware(run,actor))){assertThat(agent.getToolkit().getToolNames()).contains(FetchMcpRuntime.TOOL,LocalMcpService.PROPOSE).doesNotContain("execute_shell_command","skill_manage");agent.call("读取我指定的公开网页 https://example.com/").block(Duration.ofSeconds(60));assertThat(result.get()).contains("Example Domain");assertThat(journal.events(actor,run.id(),0,100)).anyMatch(e->e.type().equals("TOOL_COMPLETED")&&FetchMcpRuntime.TOOL.equals(e.payload().get("tool")));}
            finally{run.finish("COMPLETED");state=mcp.view(actor);mcp.enabled(actor,((Number)state.get("revision")).intValue(),false);}
            assertThat(mcp.available(actor)).isFalse();assertThatThrownBy(()->mcp.assertEnabled(actor,args)).hasMessageContaining("本人");
            Files.writeString(root.resolve("work/local-mcp-sdk-mysql.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of("passed",true,"actualSdkAndMysql",true,"actualPublicWebFetch",true,"runId",run.id(),"paidModelsCalled",false,"leftEnabled",false,"privateDirectory",mcp.view(actor).get("directory"))));
        }
    }
    @Configuration static class Config extends AgentReportLocalMysqlTest.Config {
        @Bean LocalMcpService mcp(JdbcTemplate jdbc,DataSourceTransactionManager manager,ObjectMapper json,BusinessUserDirectory users){var props=new AgentScopeProperties();props.setWorkspace(Path.of(System.getProperty("agent.report.project","..")).toAbsolutePath().resolve(".agentscope/workspace").toString());return new LocalMcpService(jdbc,manager,json,users,props,new FetchMcpRuntime(new LocalMcpProperties(),json));}
    }
}
