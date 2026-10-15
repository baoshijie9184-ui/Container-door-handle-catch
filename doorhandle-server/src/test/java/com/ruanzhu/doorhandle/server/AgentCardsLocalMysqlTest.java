package com.ruanzhu.doorhandle.server;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.card.AgentCardService;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.journal.JdbcAgentJournal;
import com.ruanzhu.doorhandle.module.ai.report.AgentReportGateway;
import com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.ChatSendMessageRequest;
import com.ruanzhu.doorhandle.module.app.mapper.*;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.app.service.impl.*;
import com.ruanzhu.doorhandle.module.detection.api.DetectionAgentReadApiImpl;
import com.ruanzhu.doorhandle.module.detection.dto.report.QualityReportDtos;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.QualityReportService;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import javax.sql.DataSource;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 真实 SDK、会话 Mapper、业务门面与 MySQL；仅模型响应和检索记忆替身化。 */
@EnabledIfSystemProperty(named="agent.cards.local.mysql",matches="true")
class AgentCardsLocalMysqlTest {
    @Test void cardsPersistRestoreAndRefreshUnderCurrentBusinessPermissions() throws Exception {
        Path root=Path.of(System.getProperty("agent.report.project","..")).toAbsolutePath().normalize();
        try(var context=new AnnotationConfigApplicationContext(Config.class)) {
            var jdbc=context.getBean(JdbcTemplate.class);var json=context.getBean(ObjectMapper.class);var sql=context.getBean(SqlSessionTemplate.class);
            var users=context.getBean(UserMapper.class);var user=users.findByUsername("inspector.demo");var otherUser=users.findByUsername("inspector.demo2");
            var actor=new AgentActor(user.getId(),user.getUsername(),AgentActor.Role.INSPECTOR);var other=new AgentActor(otherUser.getId(),otherUser.getUsername(),AgentActor.Role.INSPECTOR);
            var roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));
            SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(new TenantPrincipal(user.getId(),user.getUsername(),"",roles),null,roles));
            String task="agent-card-fixture-"+UUID.randomUUID().toString().substring(0,8),revoked=task+"-assigned";
            for(String id:List.of(task,revoked))jdbc.update("INSERT INTO detection_task(task_id,status,flow_status,created_by,assignee,total_images,processed_images,successful_images,failed_images,defect_count,review_status,review_conclusion,created_at,updated_at) VALUES(?,'COMPLETED','REVIEWED',?,?,3,3,3,0,2,'REVIEWED','PASS',NOW(),NOW())",id,id.equals(task)?actor.username():"supervisor.demo",actor.username());
            var report=context.getBean(QualityReportService.class).create(context.getBean(BusinessUserDirectory.class).current(actor.userId(),actor.username()),new QualityReportDtos.Create(task,"卡片验收报告 <script>文本</script>","私人验收草稿",UUID.randomUUID().toString()));
            var sessions=new ChatSessionServiceImpl(sql.getMapper(ChatSessionMapper.class),sql.getMapper(ChatMessageMapper.class),sql.getMapper(ChatPendingActionMapper.class),new ChatAssistantProperties(),json);
            String session=sessions.createSession(actor.username()).getSessionId();
            var detection=new DetectionAgentReadApiImpl(context.getBean(DetectionTaskMapper.class));
            var toolkit=new BusinessToolkitFactory(detection,mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json,null,context.getBean(AgentReportGateway.class));
            var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-card-mysql");var steps=new AtomicInteger();
            when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{int step=steps.getAndIncrement();String name=null;Map<String,Object> args=Map.of();
                switch(step){
                    case 0->{name="delegate_detection_task";args=Map.of("question","查询两个指定任务");}
                    case 1->{name="get_task_detail";args=Map.of("taskId",task);}
                    case 2->{name="get_task_detail";args=Map.of("taskId",revoked);}
                    case 4->{name="delegate_personal_analytics";args=Map.of("question","查询七天工作统计");}
                    case 5->{name="get_my_work_metrics";args=Map.of("days",7);}
                    case 7->{name="delegate_report_assistant";args=Map.of("question","查询指定报告");}
                    case 8->{name="get_quality_report";args=Map.of("reportId",report.reportId());}
                }
                ContentBlock block=name==null?TextBlock.builder().text("已查询授权任务和工作统计 报告仍为私人草稿 请核对业务卡片").build():ToolUseBlock.builder().id("card-call-"+step).name(name).input(args).content(json.writeValueAsString(args)).build();
                return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());});
            var settings=new AgentScopeProperties();settings.setWorkspace(root.resolve("work/agent-card-sdk").toString());
            var conversation=new AgentScopeConversationService(new RoleAgentFactory(settings,toolkit,id->model),new AgentRunRegistry(),settings,context.getBean(JdbcAgentJournal.class));
            var beans=new DefaultListableBeanFactory();beans.registerSingleton("conversation",conversation);beans.registerSingleton("reports",context.getBean(QualityReportAgentApi.class));
            var knowledge=mock(RagKnowledgeService.class);when(knowledge.retrieveContext(anyString())).thenReturn("");
            var memory=mock(Mem0Client.class);when(memory.searchMemories(any(),anyString(),anyString(),anyInt())).thenReturn(List.of());
            var chat=new AgentScopeChatServiceImpl(sessions,beans.getBeanProvider(AgentConversationApi.class),knowledge,memory,new org.springframework.core.task.SyncTaskExecutor(),new ChatAssistantProperties(),json);
            var request=new ChatSendMessageRequest();request.setSessionId(session);request.setContent("查询指定任务 七天统计及本人报告");
            var saved=chat.handleUserMessage(actor.username(),request);
            assertThat(saved.getMessageType()).isEqualTo("AGENT_CARDS");
            var envelope=json.readValue(saved.getContent(),AgentCards.Envelope.class);assertThat(envelope.cards()).hasSize(4);
            assertThat(steps.get()).isEqualTo(11);assertThat(sessions.listMessages(actor.username(),session)).anySatisfy(message->{assertThat(message.getId()).isEqualTo(saved.getId());assertThat(message.getContent()).isEqualTo(saved.getContent());});
            SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(new TenantPrincipal(otherUser.getId(),otherUser.getUsername(),"",roles),null,roles));
            assertThatThrownBy(()->sessions.listMessages(other.username(),session)).isInstanceOf(com.ruanzhu.doorhandle.common.BusinessException.class);
            SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(new TenantPrincipal(user.getId(),user.getUsername(),"",roles),null,roles));
            var cards=new AgentCardService(detection,beans.getBeanProvider(QualityReportAgentApi.class),context.getBean(BusinessUserDirectory.class));
            assertThat(cards.resolve(actor,envelope.cards())).allMatch(v->v.status().equals("OK"));
            jdbc.update("UPDATE detection_task SET assignee=?,updated_at=NOW() WHERE task_id=?",other.username(),revoked);
            var current=cards.resolve(actor,envelope.cards());assertThat(current.get(1).items()).isEmpty();assertThat(current.get(1).status()).isEqualTo("PARTIAL");
            var otherViews=cards.resolve(other,envelope.cards());assertThat(otherViews.get(0).items()).isEmpty();assertThat(otherViews.get(3).items()).isEmpty();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_report_outbox WHERE report_id=?",Long.class,report.reportId())).isZero();
            assertThat(context.getBean(JdbcAgentJournal.class).events(actor,envelope.runId(),0,100).toString()).doesNotContain("私人验收草稿","卡片验收报告");
            var evidence=new LinkedHashMap<String,Object>();evidence.put("taskId",task);evidence.put("revokedTaskId",revoked);evidence.put("reportId",report.reportId());evidence.put("sessionId",session);evidence.put("runId",envelope.runId());evidence.put("envelope",envelope);evidence.put("modelResponsesScripted",true);evidence.put("paidModelsCalled",false);evidence.put("sdkModelCalls",steps.get());evidence.put("actualMysqlAndServices",true);evidence.put("passed",true);
            Files.writeString(root.resolve("work/agent-cards-local-mysql.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(evidence));
        } finally {SecurityContextHolder.clearContext();}
    }
    @Configuration static class Config extends AgentReportLocalMysqlTest.Config {
        @Override @Bean SqlSessionTemplate sql(DataSource source)throws Exception {
            var configuration=new MybatisConfiguration();configuration.setMapUnderscoreToCamelCase(true);
            for(var mapper:List.of(DetectionTaskMapper.class,UserMapper.class,ChatSessionMapper.class,ChatMessageMapper.class,ChatPendingActionMapper.class))configuration.addMapper(mapper);
            var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(source);factory.setConfiguration(configuration);return new SqlSessionTemplate(factory.getObject());
        }
    }
}
