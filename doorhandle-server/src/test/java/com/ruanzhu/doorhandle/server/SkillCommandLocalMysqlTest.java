package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.evolution.*;
import com.ruanzhu.doorhandle.module.ai.journal.*;
import com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 仅显式启用的本机验收：实际 MySQL/SDK，使用脚本模型而非供应商 API。 */
@EnabledIfSystemProperty(named="agent.skills.commands.mysql",matches="true")
class SkillCommandLocalMysqlTest {
    @Test void slashSelectionLoadsPublishedVersionAndPersistsPrivateJournalInActualMysql()throws Exception {
        Path root=Path.of(System.getProperty("agent.report.project","..")).toAbsolutePath().normalize();
        try(var context=new AnnotationConfigApplicationContext(SkillEvolutionLocalMysqlTest.Config.class)){
            var users=context.getBean(UserMapper.class);var json=context.getBean(ObjectMapper.class);var service=context.getBean(SkillEvolutionService.class);var journal=context.getBean(JdbcAgentJournal.class);
            var employee=users.findByUsername("inspector.demo");var supervisor=users.findByUsername("supervisor.demo");
            var actor=new AgentActor(employee.getId(),employee.getUsername(),AgentActor.Role.INSPECTOR);var boss=new AgentActor(supervisor.getId(),supervisor.getUsername(),AgentActor.Role.SUPERVISOR);
            String source=json.readTree(Files.readString(root.resolve("work/agent-cards-local-mysql.json"))).path("runId").asText();
            service.capture(actor,source);String suffix=UUID.randomUUID().toString().substring(0,8),name="fixture-slash-"+suffix;
            String instructions="先确认用户明确提供任务编号 再调用已授权的任务详情查询 核对当前图片处理数量与复核状态 仅根据实际返回回答 缺少任务或权限时明确说明 不将查询结果解释为审批通过";
            var draft=new SkillDtos.Draft(name,"INSPECTOR","用户查询本人授权任务进度时使用",instructions,List.of("get_task_detail"),source,UUID.randomUUID().toString());
            var view=service.create(actor,draft);String id=view.skillId();boolean keep=Boolean.getBoolean("agent.skills.commands.keep.fixture");
            try{
                assertThat(service.availableSkills(actor)).noneMatch(s->s.skillId().equals(id));
                view=service.evaluate(actor,id,view.revision());view=service.submit(actor,id,view.revision());view=service.decide(boss,id,new SkillDtos.Decision(view.revision(),"APPROVE","命令验收样本 通用步骤及角色权限已核对",true,true));
                var settings=new AgentScopeProperties();settings.setWorkspace(root.resolve("work/skill-commands-sdk").toString());
                var calls=new AtomicInteger();var captured=new AtomicReference<List<Msg>>();var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-command-mysql");
                when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{calls.incrementAndGet();captured.set(inv.getArgument(0));return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("已按选定技能核对问题 未执行审批").build())).finishReason("stop").build());});
                var factory=new RoleAgentFactory(settings,new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json),key->model,service);
                var engine=new AgentScopeConversationService(factory,new AgentRunRegistry(),settings,journal);
                var listed=engine.start(actor,"slash-list-"+suffix,List.of(new AgentConversationApi.Message("user","/skills")),"",e->{});
                assertThat(listed.result().get()).contains(name);assertThat(calls).hasValue(0);
                var loaded=engine.start(actor,"slash-load-"+suffix,List.of(new AgentConversationApi.Message("user","/"+name)),"",e->{});
                assertThat(loaded.result().get()).contains("已加载",instructions);assertThat(calls).hasValue(0);
                var applied=engine.start(actor,"slash-use-"+suffix,List.of(new AgentConversationApi.Message("user","/skill "+id+" 查询当前任务进度")),"",e->{});
                assertThat(applied.result().get(20,TimeUnit.SECONDS)).contains("选定技能");assertThat(calls).hasValue(1);
                assertThat(captured.get().stream().map(Msg::getTextContent).collect(java.util.stream.Collectors.joining("\n"))).contains("<selected_skill>",instructions,"查询当前任务进度");
                assertThat(service.get(actor,id).useCount()).isEqualTo(2);
                var events=journal.events(actor,applied.runId(),0,100);assertThat(events).anySatisfy(e->{assertThat(e.type()).isEqualTo("SKILL_COMMAND_LOADED");assertThat(e.payload()).containsEntry("skillId",id).containsEntry("version",1);});
                assertThat(events.toString()).doesNotContain(instructions,"查询当前任务进度");assertThatThrownBy(()->journal.get(boss,applied.runId())).hasMessageContaining("404");
                assertThat(service.get(actor,id).audit()).filteredOn(row->"COMMAND_LOAD".equals(row.get("action_name"))).hasSize(2);
                var denied=engine.start(boss,"slash-other-"+suffix,List.of(new AgentConversationApi.Message("user","/skill "+id)),"",e->{});assertThat(denied.result().get()).contains("不可用");assertThat(calls).hasValue(1);
                Files.writeString(root.resolve("work/skill-command-local-mysql.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of("skillId",id,"name",name,"sourceRunId",source,"listRunId",listed.runId(),"loadRunId",loaded.runId(),"useRunId",applied.runId(),"paidModelsCalled",false,"actualSdkAndMysql",true,"keptForBrowser",keep,"passed",true)));
            }finally{
                var current=service.get(actor,id);if(!keep&&current.activeVersion()!=null)service.archive(boss,id,new SkillDtos.Command(current.revision(),"命令验收后停用 保留历史"));
            }
        }
    }
}
