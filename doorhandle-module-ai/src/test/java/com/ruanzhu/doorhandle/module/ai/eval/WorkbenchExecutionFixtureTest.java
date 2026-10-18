package com.ruanzhu.doorhandle.module.ai.eval;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import reactor.core.publisher.Flux;
import java.nio.file.Path;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class WorkbenchExecutionFixtureTest {
    @TempDir Path workspace;
    final ObjectMapper json=new ObjectMapper();
    @Test @Timeout(480)
    void twoOwnersYieldThenDispatchRealProfessionalsAndRetainTheirPrivateHistory() throws Exception {
        var model=scripted();
        String mysql=System.getProperty("agent.workbench.mysqlConfig","");
        try(var f=new WorkbenchExecutionFixture(Path.of(System.getProperty("agent.eval.project","..")).toAbsolutePath().normalize(),workspace,"scripted-workbench",id->model,mysql.isBlank()?null:Path.of(mysql))) {
            for(var actor:List.of(f.employee,f.supervisor)) {
                String session="plan-"+actor.userId();
                f.start(actor,session,UUID.randomUUID().toString(),"/plan 只读查询任务 "+f.task(actor)+" 的状态与缺陷数量，使用一个专业子任务").result().get(90,java.util.concurrent.TimeUnit.SECONDS);
                f.waitFor(actor,session,"WAITING_PLAN",10);
                assertThat(f.calls(actor)).isZero();
                assertThat(f.events(actor,session).stream().map(event->event.type()).toList()).contains("AGENT_YIELDED","MODEL_YIELDED").doesNotContain("AGENT_ERROR","MODEL_ERROR");
                org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(30)).until(()->f.registry.acquire(actor.userId()+":"+(actor.supervisor()?"supervisor-main":"employee-main")+":"+session));
                f.registry.release(actor.userId()+":"+(actor.supervisor()?"supervisor-main":"employee-main")+":"+session);
            }
            var permits=(java.util.concurrent.Semaphore)org.springframework.test.util.ReflectionTestUtils.getField(f.workbench,"slots");
            assertThat(permits.availablePermits()).isEqualTo(2);
            assertThatThrownBy(()->f.workbench.list(f.supervisor,"plan-"+f.employee.userId())).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
            for(var actor:List.of(f.employee,f.supervisor))f.approve(actor,"plan-"+actor.userId());
            for(var actor:List.of(f.employee,f.supervisor)) {
                String session="plan-"+actor.userId();f.waitFor(actor,session,"COMPLETED",120);
                assertThat(f.calls(actor)).isEqualTo(1);
                assertThat(f.item(actor,session,"EXECUTION").data().get("result").toString()).contains(f.task(actor),actor.supervisor()?"13":"7");
                var child=f.item(actor,session,"CHILD");assertThat(child.status()).isEqualTo("COMPLETED");
                f.workbench.command(actor,session,child.id(),child.revision(),UUID.randomUUID().toString(),"child-message",Map.of("content","只使用先前详情补充六类缺陷分布是否已提供，不重复查询"));
                org.awaitility.Awaitility.await().atMost(Duration.ofSeconds(60)).until(()->{f.workbench.dispatch();return f.item(actor,session,"CHILD").status().equals("COMPLETED");});
                assertThat(f.item(actor,session,"CHILD").data().get("result").toString()).contains("未知");
                assertThat(f.calls(actor)).isEqualTo(1);
                assertThat(f.journal.list(actor,"child-"+child.id(),null,10)).hasSize(2);
            }
        }
    }
    Model scripted() {
        var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-workbench");var sequence=new AtomicInteger();
        when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{
            List<Msg> messages=inv.getArgument(0);
            String transcript=messages.stream().map(Msg::getTextContent).reduce("",(left,right)->left+"\n"+right);
            List<ToolSchema> schemas=inv.getArgument(1);var names=schemas.stream().map(ToolSchema::getName).collect(java.util.stream.Collectors.toSet());
            var results=messages.stream().flatMap(message->message.getContentBlocks(ToolResultBlock.class).stream()).toList();
            String name=null;Map<String,Object> input=Map.of();String reply=null;
            if(names.stream().noneMatch(tool->tool.startsWith("delegate_"))&&!names.contains("get_task_detail")) {name="submit_plan";input=Map.of("title","合成只读验收计划","text","经批准后用一个专业子任务查询单任务详情再汇总");}
            else if(names.contains("get_task_detail")) {
                var previous=results.stream().filter(result->"get_task_detail".equals(result.getName())).reduce((a,b)->b);
                if(previous.isEmpty()) {name="get_task_detail";input=Map.of("taskId",transcript.contains("det_eval_supervisor")?"det_eval_supervisor":"det_eval_employee");}
                else {var facts=json.readTree(text(previous.get())).path("data");reply=facts.path("taskId").asText()+" COMPLETED 缺陷总数 "+facts.path("defectCount").asInt()+" 当前复核 PENDING 待复核 六类分布未知";}
            } else {
                var child=results.stream().filter(result->"get_background_task".equals(result.getName())||result.getName().startsWith("delegate_")).reduce((a,b)->b);
                if(child.isPresent()) {
                    var state=json.readTree(text(child.get()));
                    if(state.path("status").asText().equals("COMPLETED"))reply=state.path("data").path("result").asText();
                    else {name="get_background_task";input=Map.of("itemId",state.path("id").asText());}
                } else {name=names.contains("delegate_detection_quality")?"delegate_detection_quality":"delegate_detection_task";input=Map.of("question",transcript.contains("det_eval_supervisor")?"只读查询 det_eval_supervisor 的状态与缺陷总数":"只读查询 det_eval_employee 的状态与缺陷总数");}
            }
            ContentBlock block=name==null?TextBlock.builder().text(reply).build():ToolUseBlock.builder().id("wb-script-"+sequence.incrementAndGet()).name(name).input(input).content(json.writeValueAsString(input)).build();
            return Flux.just(ChatResponse.builder().content(List.of(block)).finishReason(name==null?"stop":"tool_calls").build());
        });return model;
    }
    String text(ToolResultBlock result){return result.getOutput().stream().filter(TextBlock.class::isInstance).map(TextBlock.class::cast).map(TextBlock::getText).reduce("",String::concat);}
}
