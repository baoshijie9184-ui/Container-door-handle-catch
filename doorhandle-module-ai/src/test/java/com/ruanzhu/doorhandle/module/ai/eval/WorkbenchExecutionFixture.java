package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.*;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.ai.workbench.*;
import io.agentscope.core.model.Model;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.security.access.AccessDeniedException;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Function;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Real conversation, workbench, JDBC state, journal and scheduler; synthetic App/identity/business facades. */
final class WorkbenchExecutionFixture implements AutoCloseable {
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    final AgentActor employee=new AgentActor(990001,"wb.eval.employee",AgentActor.Role.INSPECTOR);
    final AgentActor supervisor=new AgentActor(990002,"wb.eval.supervisor",AgentActor.Role.SUPERVISOR);
    final JdbcTemplate jdbc;
    final AgentWorkbenchService workbench;
    final JdbcAgentJournal journal;
    final AgentScopeConversationService conversations;
    final AgentRunRegistry registry=new AgentRunRegistry();
    final Map<String,Long> owners=new ConcurrentHashMap<>();
    final Map<String,List<AgentConversationApi.Message>> history=new ConcurrentHashMap<>();
    final Map<String,AgentConversationApi.Run> admissions=new ConcurrentHashMap<>();
    final List<Map<String,Object>> businessCalls=new CopyOnWriteArrayList<>();
    final List<Throwable> failures=new CopyOnWriteArrayList<>();
    final String databaseKind;
    final com.zaxxer.hikari.HikariDataSource pool;

    @SuppressWarnings("unchecked")
    WorkbenchExecutionFixture(Path project,Path workspace,String modelId,Function<String,Model> models,Path mysql) throws Exception {
        var source=new DriverManagerDataSource("jdbc:h2:mem:workbench_live_"+UUID.randomUUID()+";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1","sa","");
        javax.sql.DataSource dataSource=source;
        if(mysql!=null) {
            if(!mysql.toRealPath().startsWith(project.resolve("work").toRealPath()))throw new IllegalArgumentException("Private project-owned MySQL config required");
            var config=json.readTree(mysql.toFile());String database=config.path("database").asText();
            if(!database.matches("doorhandle_wb_live_[a-f0-9]{10}")||!config.path("url").asText().startsWith("jdbc:mysql://127.0.0.1:13310/"+database+"?"))throw new IllegalArgumentException("Only an isolated workbench verification database is allowed");
            pool=new com.zaxxer.hikari.HikariDataSource();pool.setJdbcUrl(config.path("url").asText());pool.setUsername(config.path("username").asText());pool.setPassword(config.path("password").asText());pool.setMaximumPoolSize(6);pool.setMinimumIdle(1);dataSource=pool;databaseKind="MYSQL_ISOLATED";
            var isolated=new JdbcTemplate(pool);
            if(!database.equals(isolated.queryForObject("SELECT DATABASE()",String.class))||isolated.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",Integer.class)!=0)throw new IllegalArgumentException("Use an empty verification database, never replay an earlier experiment");
        } else {pool=null;databaseKind="H2_SYNTHETIC";}
        jdbc=new JdbcTemplate(dataSource);
        for(String relative:List.of("doorhandle-module-ai/src/main/resources/db/migration-V16-agentscope-run-journal.sql","sql/mysql/migration-V37-agent-workbench.sql")) {
            String ddl=Files.readString(project.resolve(relative));
            if(mysql==null)ddl=ddl.replaceAll("(?m)^--.*$", "").replace(" COLLATE utf8mb4_bin","").replace(" ENGINE=InnoDB DEFAULT CHARSET=utf8mb4","")
                    .replace("payload_json JSON","payload_json VARCHAR(8192)").replaceAll("(?m)^(\\s*)UNIQUE KEY (\\w+)\\s*(\\([^\\n]+\\))", "$1CONSTRAINT $2 UNIQUE $3").replaceAll("(?m)^\\s*KEY .*\\n","").replaceAll(",\\s*\\)",")");
            for(String statement:ddl.split(";"))if(!statement.isBlank())jdbc.execute(statement);
        }
        var tx=new DataSourceTransactionManager(dataSource);
        var journalSettings=new AgentJournalProperties();journalSettings.setEnabled(true);
        journal=new JdbcAgentJournal(jdbc,tx,json,journalSettings);journal.verifySchema();
        var users=mock(BusinessUserDirectory.class);
        when(users.current(anyLong(),anyString())).thenAnswer(inv->{long id=inv.getArgument(0);String name=inv.getArgument(1);
            var actor=List.of(employee,supervisor).stream().filter(candidate->candidate.userId()==id&&candidate.username().equals(name)).findFirst().orElseThrow(()->new AccessDeniedException("Unknown fixture identity"));
            return new BusinessUserDirectory.Identity(actor.userId(),actor.username(),actor.supervisor());
        });
        var detection=mock(DetectionAgentReadApi.class);
        when(detection.task(any(),anyString())).thenAnswer(inv->{AgentActor actor=inv.getArgument(0);String task=inv.getArgument(1);
            businessCalls.add(Map.of("actorId",actor.userId(),"taskId",task,"tool","get_task_detail"));
            if(!task.equals(task(actor)))throw new SecurityException("Fixture task outside scope");
            return new DetectionAgentReadApi.TaskView(task,"COMPLETED","PENDING_REVIEW","fixture-camera",5,5,actor.supervisor()?13:7,"PENDING",null,LocalDateTime.of(2026,10,18,12,0));
        });
        when(detection.tasks(any(),anyInt(),anyInt(),anyBoolean())).thenAnswer(inv->{businessCalls.add(Map.of("tool","unexpected_list"));throw new SecurityException("Not requested");});
        when(detection.metrics(any(),anyInt())).thenAnswer(inv->{businessCalls.add(Map.of("tool","unexpected_metrics"));throw new SecurityException("Not requested");});
        var properties=new AgentScopeProperties();properties.setWorkspace(workspace.toString());properties.setModel(modelId);properties.setMaxIters(5);
        var factory=new RoleAgentFactory(properties,new BusinessToolkitFactory(detection,mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json),models);
        var app=mock(WorkbenchSessionApi.class);
        doAnswer(inv->{owned(inv.getArgument(0),inv.getArgument(1));return null;}).when(app).assertOwned(any(),anyString());
        when(app.externalJobs(any(),anyString())).thenReturn(List.of());
        var provider=mock(ObjectProvider.class);when(provider.getObject()).thenReturn(app);
        var settings=new WorkbenchProperties();settings.setEnabled(true);settings.setFiles(false);settings.setForks(false);
        workbench=new AgentWorkbenchService(new WorkbenchStore(jdbc,tx,json),settings,users,provider,factory,journal);
        org.springframework.test.util.ReflectionTestUtils.invokeMethod(workbench,"validate");
        conversations=new AgentScopeConversationService(factory,registry,properties,journal);conversations.setWorkbench(workbench);
        doAnswer(inv->{AgentActor actor=inv.getArgument(0);String session=inv.getArgument(1),request=inv.getArgument(2),content=inv.getArgument(3);
            owned(actor,session);synchronized(admissions){if(!admissions.containsKey(request))start(actor,session,request,content);}return null;
        }).when(app).continueSession(any(),anyString(),anyString(),anyString());
    }
    void owned(AgentActor actor,String session){if(!Objects.equals(owners.get(session),actor.userId()))throw new AccessDeniedException("Fixture conversation belongs to another account");}
    AgentConversationApi.Run start(AgentActor actor,String session,String request,String question) {
        owners.putIfAbsent(session,actor.userId());owned(actor,session);
        var messages=history.computeIfAbsent(session,ignored->new CopyOnWriteArrayList<>());
        messages.add(new AgentConversationApi.Message("user",question));
        AgentConversationApi.Run run;
        try{run=conversations.start(actor,session,List.copyOf(messages),"",event->{},"CHAT",request);}
        catch(RuntimeException error){messages.remove(messages.size()-1);throw error;}
        admissions.put(request,run);
        run.result().whenComplete((reply,error)->{if(error==null)messages.add(new AgentConversationApi.Message("assistant",reply));else failures.add(error);});
        return run;
    }
    AgentWorkbenchApi.Item item(AgentActor actor,String session,String kind){return workbench.list(actor,session).stream().filter(row->row.kind().equals(kind)).findFirst().orElseThrow();}
    Map<String,Object> execution(AgentActor actor,String session) throws Exception {
        return json.readValue(jdbc.queryForObject("SELECT payload FROM agent_workbench_item WHERE user_id=? AND session_id=? AND kind='EXECUTION'",String.class,actor.userId(),session),Map.class);
    }
    void waitFor(AgentActor actor,String session,String phase,int seconds) {
        try {org.awaitility.Awaitility.await().pollInterval(Duration.ofMillis(100)).atMost(Duration.ofSeconds(seconds)).until(()->{
            assertThat(failures).isEmpty();workbench.dispatch();
            var job=item(actor,session,"EXECUTION");if(job.status().equals("NEEDS_REVIEW"))throw new AssertionError("Execution needs review; do not replay automatically");
            return job.status().equals(phase)&&(!phase.startsWith("WAITING_")||Boolean.TRUE.equals(execution(actor,session).get("yieldReady")));
        });} catch(AssertionError|RuntimeException error){
            System.out.println("FIXTURE_FAILURE_ITEMS "+workbench.list(actor,session));
            for(var run:journal.list(actor,null,null,50))System.out.println("FIXTURE_FAILURE_RUN "+run+" "+journal.events(actor,run.runId(),0,100));
            throw error;
        }
    }
    void approve(AgentActor actor,String session){var plan=item(actor,session,"PLAN");workbench.command(actor,session,plan.id(),plan.revision(),UUID.randomUUID().toString(),"approve-plan",Map.of());}
    String task(AgentActor actor){return actor.supervisor()?"det_eval_supervisor":"det_eval_employee";}
    long calls(AgentActor actor){return businessCalls.stream().filter(call->Objects.equals(call.get("actorId"),actor.userId())).count();}
    List<AgentJournal.EventView> events(AgentActor actor,String session){
        var result=new ArrayList<AgentJournal.EventView>();
        for(var run:journal.list(actor,session,null,50)) {
            long after=0;
            while(true){var page=journal.events(actor,run.runId(),after,100);result.addAll(page);if(page.size()<100)break;after=page.get(page.size()-1).sequence();}
        }
        return result;
    }
    @Override public void close(){try{for(var run:admissions.values())if(!run.result().isDone())run.cancel().run();workbench.close();}finally{if(pool!=null)pool.close();else jdbc.execute("SHUTDOWN");}}
}
