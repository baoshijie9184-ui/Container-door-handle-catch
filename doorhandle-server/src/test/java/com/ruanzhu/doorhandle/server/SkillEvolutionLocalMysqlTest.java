package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.evolution.*;
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
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@EnabledIfSystemProperty(named="agent.skills.local.mysql",matches="true")
class SkillEvolutionLocalMysqlTest {
    @Test void nativeProposalEvaluationPublishUseRollbackAndPrivateSourceWorkInActualMysql()throws Exception {
        Path root=Path.of(System.getProperty("agent.report.project","..")).toAbsolutePath();
        try(var context=new AnnotationConfigApplicationContext(Config.class)){
            var users=context.getBean(UserMapper.class);var json=context.getBean(ObjectMapper.class);var service=context.getBean(SkillEvolutionService.class);var journal=context.getBean(JdbcAgentJournal.class);
            var staff=users.findByUsername("inspector.demo");var supervisor=users.findByUsername("supervisor.demo");var actor=new AgentActor(staff.getId(),staff.getUsername(),AgentActor.Role.INSPECTOR);var boss=new AgentActor(supervisor.getId(),supervisor.getUsername(),AgentActor.Role.SUPERVISOR);
            for(var previous:service.list(boss))if(previous.name().startsWith("fixture-progress-")&&previous.activeVersion()!=null)service.archive(boss,previous.skillId(),new SkillDtos.Command(previous.revision(),"停用此前未完成的验收样本 保留历史"));
            var fixture=json.readTree(Files.readString(root.resolve("work/agent-cards-local-mysql.json")));String source=fixture.path("runId").asText();service.capture(actor,source);
            String suffix=UUID.randomUUID().toString().substring(0,8),name="fixture-progress-"+suffix;
            var args=Map.<String,Object>of("name",name,"targetRole","INSPECTOR","description","用户询问授权任务进度时使用此经验","instructions","先确认用户明确提供任务编号 再调用已授权的任务详情查询 核对当前图片处理数量与复核状态 仅根据实际返回回答 缺少任务或权限时明确说明 不将查询结果解释为审批通过","tools",List.of("get_task_detail"),"sourceRunId",source);
            var settings=new AgentScopeProperties();settings.setWorkspace(root.resolve("work/skill-evolution-sdk").toString());var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-skill-mysql");var steps=new AtomicInteger();
            when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{ContentBlock block=steps.getAndIncrement()==0?ToolUseBlock.builder().id("skill-proposal-call").name(SkillEvolutionService.PROPOSE).input(args).content(json.writeValueAsString(args)).build():TextBlock.builder().text("私人技能草稿已提议 尚未评测或发布").build();return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());});
            var factory=new RoleAgentFactory(settings,new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json),id->model,service);
            var run=journal.begin(actor,"skill-fixture-"+suffix,"employee-main","CHAT","proposal-"+suffix,"scripted-skill-mysql");
            try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(actor,null,new AgentJournalMiddleware(run,actor))){agent.call("我已经授权来源 请提炼私人技能草稿").block(Duration.ofSeconds(15));}finally{run.finish("COMPLETED");}
            var skill=service.list(actor).stream().filter(v->v.name().equals(name)).findFirst().orElseThrow();String privateId=skill.skillId();assertThat(skill.activeVersion()).isNull();assertThatThrownBy(()->service.get(boss,privateId)).hasMessageContaining("无权限");
            skill=service.evaluate(actor,skill.skillId(),skill.revision());skill=service.submit(actor,skill.skillId(),skill.revision());assertThat(service.get(boss,skill.skillId()).versions().get(0).sourceRunId()).isNull();
            skill=service.decide(boss,skill.skillId(),new SkillDtos.Decision(skill.revision(),"APPROVE","真实数据库验收 通用步骤已核对及脱敏",true,true));
            String id=skill.skillId();var nativeSkill=service.repository(actor).getAllSkills().stream().filter(s->s.getSkillContent().contains(name)).findFirst().orElseThrow();steps.set(0);
            when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{ContentBlock block=steps.getAndIncrement()==0?ToolUseBlock.builder().id("skill-load-call").name(SkillEvolutionService.LOAD).input(Map.of("skillId",nativeSkill.getSkillId(),"path","SKILL.md")).content(json.writeValueAsString(Map.of("skillId",nativeSkill.getSkillId(),"path","SKILL.md"))).build():TextBlock.builder().text("已读取发布技能 无业务写入").build();return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(block)).build());});
            steps.set(0);
            var load=journal.begin(actor,"skill-load-"+suffix,"employee-main","CHAT","load-"+suffix,"scripted-skill-mysql");
            try(var agent=(io.agentscope.harness.agent.HarnessAgent)factory.create(actor,null,new AgentJournalMiddleware(load,actor))){assertThat(agent.getToolkit().getToolNames()).doesNotContain("execute_shell_command","skill_manage","approve_report");agent.call("读取任务查询经验").block(Duration.ofSeconds(15));}finally{load.finish("COMPLETED");}
            skill=service.get(actor,id);assertThat(skill.useCount()).isEqualTo(1);assertThat(journal.events(actor,load.id(),0,100)).anyMatch(e->e.type().equals("TOOL_COMPLETED")&&SkillEvolutionService.LOAD.equals(e.payload().get("tool")));
            var revised=new SkillDtos.Draft(name,"INSPECTOR",(String)args.get("description"),(String)args.get("instructions")+" 复核缺陷数量与图片数量的不同含义",List.of("get_task_detail"),source,UUID.randomUUID().toString());
            skill=service.revise(actor,id,skill.revision(),revised);skill=service.evaluate(actor,id,skill.revision());skill=service.submit(actor,id,skill.revision());skill=service.decide(boss,id,new SkillDtos.Decision(skill.revision(),"APPROVE","第二版已核对",true,true));
            skill=service.rollback(boss,id,new SkillDtos.Rollback(skill.revision(),1,"回退验收"));assertThat(skill.activeVersion()).isEqualTo(1);
            skill=service.archive(boss,id,new SkillDtos.Command(skill.revision(),"验收后暂停 不影响实际助手"));assertThat(service.repository(actor).getAllSkills()).noneMatch(s->s.getName().equals(nativeSkill.getName()));
            // 第三版保留待审，浏览器验收独立发布及再次停用。
            revised=new SkillDtos.Draft(name,"INSPECTOR",revised.description(),revised.instructions()+" 完成查询后提示用户核对业务页面",revised.tools(),source,UUID.randomUUID().toString());
            skill=service.revise(actor,id,skill.revision(),revised);skill=service.evaluate(actor,id,skill.revision());skill=service.submit(actor,id,skill.revision());
            Files.writeString(root.resolve("work/skill-evolution-local-mysql.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of("skillId",id,"name",name,"sourceRunId",source,"proposalRunId",run.id(),"loadRunId",load.id(),"expectedRevision",skill.revision(),"paidModelsCalled",false,"actualSdkAndMysql",true,"passed",true)));
        }
    }
    @Configuration static class Config extends AgentReportLocalMysqlTest.Config {
        @Bean SkillEvolutionService evolution(JdbcTemplate jdbc,DataSourceTransactionManager manager,ObjectMapper json,BusinessUserDirectory users,JdbcAgentJournal journal){return new SkillEvolutionService(jdbc,manager,json,users,journal);}
    }
}
