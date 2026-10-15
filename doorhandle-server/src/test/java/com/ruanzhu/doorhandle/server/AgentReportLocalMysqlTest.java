package com.ruanzhu.doorhandle.server;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.*;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import com.ruanzhu.doorhandle.module.ai.report.*;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.detection.api.QualityReportAgentApiImpl;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.repository.QualityReportRepository;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.QualityReportService;
import com.ruanzhu.doorhandle.module.system.api.BusinessUserDirectoryImpl;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import io.agentscope.core.tool.*;
import io.github.cdimascio.dotenv.Dotenv;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import javax.sql.DataSource;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 真实 SDK → 工具 → 来源关联 → 业务事务 → MySQL。仅模型输出脚本化，不访问供应商。 */
@EnabledIfSystemProperty(named="agent.report.local.mysql",matches="true")
class AgentReportLocalMysqlTest {
    @Test void actualSdkDraftPersistsWithOwnerAuditAndTraceAndCannotApprove() throws Exception {
        Path root=Path.of(System.getProperty("agent.report.project",".." )).toAbsolutePath().normalize();
        try(var context=new AnnotationConfigApplicationContext(Config.class)){
            var jdbc=context.getBean(JdbcTemplate.class);var json=context.getBean(ObjectMapper.class);var users=context.getBean(UserMapper.class);
            var user=users.findByUsername("inspector.demo");var otherUser=users.findByUsername("inspector.demo2");var bossUser=users.findByUsername("supervisor.demo");
            var actor=new AgentActor(user.getId(),user.getUsername(),AgentActor.Role.INSPECTOR);
            var other=new AgentActor(otherUser.getId(),otherUser.getUsername(),AgentActor.Role.INSPECTOR);
            var boss=new AgentActor(bossUser.getId(),bossUser.getUsername(),AgentActor.Role.SUPERVISOR);
            String task="agent-report-fixture-"+UUID.randomUUID().toString().substring(0,8);
            jdbc.update("INSERT INTO detection_task(task_id,status,flow_status,created_by,assignee,total_images,processed_images,successful_images,failed_images,review_status,review_conclusion,created_at,updated_at) VALUES(?,'COMPLETED','REVIEWED',?,?,3,3,3,0,'REVIEWED','PASS',NOW(),NOW())",task,actor.username(),actor.username());
            var journal=context.getBean(JdbcAgentJournal.class);var api=context.getBean(QualityReportAgentApi.class);var gateway=context.getBean(AgentReportGateway.class);
            var run=journal.begin(actor,task,"employee-main","AGUI",task,"scripted-mysql-model");
            var args=Map.<String,Object>of("taskId",task,"title","真实 MySQL Agent 草稿","narrative","fixture 草稿，不代表审批通过");
            var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-mysql-model");var step=new AtomicInteger();
            when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
                int index=step.getAndIncrement();ContentBlock block;
                if(index==0)block=ToolUseBlock.builder().id("delegate-report").name("delegate_report_assistant").input(Map.of("question","保存本人报告草稿")).content("{\"question\":\"保存本人报告草稿\"}").build();
                else if(index==1)block=ToolUseBlock.builder().id("mysql-draft-call").name("create_report_draft").input(args).content(json.writeValueAsString(args)).build();
                else block=TextBlock.builder().text("本人草稿已保存，尚未提交审批").build();
                return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());
            });
            var toolkit=new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json,null,gateway);
            var settings=new AgentScopeProperties();settings.setWorkspace(root.resolve("work/agent-report-sdk-fixture").toString());
            var factory=new RoleAgentFactory(settings,toolkit,id->model);
            String reportId;
            try{
                try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(actor,null,new AgentJournalMiddleware(run,actor,false,true,true))){
                    assertThat(agent.call("请为任务 "+task+" 保存本人报告草稿").block(Duration.ofSeconds(20)).getTextContent()).contains("尚未提交审批");
                }
                var page=api.list(actor,1,20,"DRAFT",task);assertThat(page.records()).hasSize(1);reportId=page.records().get(0).reportId();
                assertThat(api.get(actor,reportId).report().status()).isEqualTo("DRAFT");
                var again=gateway.write(actor,run.id(),"mysql-second-call","create_report_draft",new LinkedHashMap<>(args));assertThat(again.report().reportId()).isEqualTo(reportId);
                assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_report_agent_origin WHERE report_id=?",Long.class,reportId)).isEqualTo(1);
                var audit=context.getBean(QualityReportService.class).audit(new BusinessUserDirectory.Identity(actor.userId(),actor.username(),false),reportId);
                assertThat(audit).hasSize(1);assertThat(audit.get(0).runId()).isEqualTo(run.id());assertThat(audit.get(0).callId()).isEqualTo("mysql-draft-call");
                assertThatThrownBy(()->api.get(other,reportId)).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
                assertThatThrownBy(()->api.get(boss,reportId)).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
                assertThatThrownBy(()->gateway.write(other,run.id(),"foreign-call","create_report_draft",args)).isInstanceOf(SecurityException.class);
                var events=journal.events(actor,run.id(),0,100);
                assertThat(events).anySatisfy(e->{assertThat(e.type()).isEqualTo("AUTHORIZATION_ALLOWED");assertThat(e.payload()).containsEntry("tool","create_report_draft").containsEntry("policyVersion",AgentReportGateway.POLICY);});
                assertThat(events).anySatisfy(e->{assertThat(e.type()).isEqualTo("TOOL_COMPLETED");assertThat(e.payload()).containsEntry("tool","create_report_draft");});
                assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_report_outbox WHERE report_id=?",Long.class,reportId)).isZero();
                assertThat(toolkit.create(actor,factory.definitions(actor).get(4),run.id()).getToolNames()).doesNotContain("approve_report","submit_report","export_report");
                var edited=gateway.write(actor,run.id(),"mysql-edit-call","edit_report_draft",Map.of("reportId",reportId,"expectedVersion",1,"title","修改后草稿","narrative","fixture 修订意见"));
                assertThat(edited.report().version()).isEqualTo(2);
            }finally{run.finish("COMPLETED");}
            assertThatThrownBy(()->gateway.write(actor,run.id(),"late-call","create_report_draft",args)).isInstanceOf(SecurityException.class);
            Files.createDirectories(root.resolve("work"));
            Files.writeString(root.resolve("work/agent-report-local-mysql.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of(
                    "taskId",task,"reportId",reportId,"runId",run.id(),"sdkModelCalls",step.get(),"actualMysqlAndServices",true,"modelResponsesScripted",true,"paidModelsCalled",false,"passed",true,"fixtureDataRetained",true)));
        }
    }
    @Configuration @EnableTransactionManagement static class Config {
        @Bean DataSource source(){
            var root=Path.of(System.getProperty("agent.report.project","..")).toAbsolutePath();var env=Dotenv.configure().directory(root.toString()).load();String url=env.get("DB_URL");
            if(!url.matches("jdbc:mysql://(?:localhost|127\\.0\\.0\\.1):3306/doorhandledb\\?.+"))throw new IllegalArgumentException("仅允许本机 doorhandledb");
            return new DriverManagerDataSource(url,env.get("DB_USERNAME"),env.get("DB_PASSWORD"));
        }
        @Bean JdbcTemplate jdbc(DataSource source){return new JdbcTemplate(source);}
        @Bean DataSourceTransactionManager transaction(DataSource source){return new DataSourceTransactionManager(source);}
        @Bean ObjectMapper json(){return new ObjectMapper().findAndRegisterModules().disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS).setSerializationInclusion(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL);}
        @Bean SqlSessionTemplate sql(DataSource source)throws Exception{var config=new MybatisConfiguration();config.setMapUnderscoreToCamelCase(true);config.addMapper(DetectionTaskMapper.class);config.addMapper(UserMapper.class);var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(source);factory.setConfiguration(config);return new SqlSessionTemplate(factory.getObject());}
        @Bean DetectionTaskMapper tasks(SqlSessionTemplate sql){return sql.getMapper(DetectionTaskMapper.class);}
        @Bean UserMapper users(SqlSessionTemplate sql){return sql.getMapper(UserMapper.class);}
        @Bean BusinessUserDirectory directory(UserMapper users){return new BusinessUserDirectoryImpl(users);}
        @Bean QualityReportRepository repository(JdbcTemplate jdbc){return new QualityReportRepository(jdbc);}
        @Bean QualityReportService reports(QualityReportRepository repository,DetectionTaskMapper tasks,BusinessUserDirectory directory,ObjectMapper json){return new QualityReportService(repository,tasks,directory,new DetectionTaskAccessPolicy(),json);}
        @Bean QualityReportAgentApi api(QualityReportService service,JdbcTemplate jdbc){return new QualityReportAgentApiImpl(service,jdbc);}
        @Bean JdbcAgentJournal journal(JdbcTemplate jdbc,DataSourceTransactionManager transaction,ObjectMapper json){var settings=new AgentJournalProperties();settings.setEnabled(true);return new JdbcAgentJournal(jdbc,transaction,json,settings);}
        @Bean AgentReportGateway gateway(QualityReportAgentApi api,JdbcAgentJournal journal,JdbcTemplate jdbc,DataSourceTransactionManager transaction,ObjectMapper json){return new AgentReportGateway(api,journal,jdbc,transaction,json);}
    }
}
