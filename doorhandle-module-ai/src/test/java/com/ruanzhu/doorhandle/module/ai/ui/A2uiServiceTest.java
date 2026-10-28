package com.ruanzhu.doorhandle.module.ai.ui;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.card.AgentCardService;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class A2uiServiceTest {
    final AgentActor actor=new AgentActor(19,"supervisor.demo",AgentActor.Role.SUPERVISOR);
    final AgentCardService cards=mock(AgentCardService.class);
    final AgentChatSessionApi sessions=mock(AgentChatSessionApi.class);
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    final A2uiService service=new A2uiService(cards,sessions,json);
    final List<AgentCards.Reference> refs=List.of(new AgentCards.Reference("METRICS","get_department_work_metrics",List.of(),7));
    final A2uiService.Query query=new A2uiService.Query("sess_demo",refs);
    void available(){when(cards.resolve(actor,refs)).thenReturn(List.of(new AgentCards.View("METRICS",refs.get(0).tool(),"OK",List.of(),Map.of("taskCount",12,"imageCount",100,"processedImageCount",65,"defectCount",8),null,null,"SINGLE_ENTERPRISE","按创建时间统计","2026-10-28T11:00:00")));}
    @Test void projectsAuthorizedStatisticsIntoVersionedIncrementalMessages()throws Exception{
        available();var result=service.resolve(actor,query);String text=json.writeValueAsString(result);
        assertThat(result.get("version")).isEqualTo("v0.9.1");assertThat((List<?>)result.get("messages")).hasSize(3);
        assertThat(text).contains("createSurface","updateComponents","updateDataModel","Metric","BarChart","Progress","TextField","FOLLOW_UP","100","65");
        assertThat(text).doesNotContain("apiKey","script","iframe");verify(sessions).assertOwned(actor,"sess_demo");verify(cards).resolve(actor,refs);verifyNoMoreInteractions(cards);verify(sessions,never()).start(any(),any(),any(),any(),any());
    }
    @Test void rejectsUnownedSessionBeforeAnyBusinessRead(){
        doThrow(new SecurityException()).when(sessions).assertOwned(actor,"sess_demo");
        assertThatThrownBy(()->service.resolve(actor,query)).isInstanceOf(SecurityException.class);verifyNoInteractions(cards);
    }
    @Test void actionRevalidatesPermissionAndOnlyPreparesAnOrdinaryUserQuestion(){
        available();var result=service.resolve(actor,query);var first=(Map<?,?>)((List<?>)result.get("messages")).get(0);var create=(Map<?,?>)first.get("createSurface");
        var action=new A2uiService.Action("FOLLOW_UP",(String)create.get("surfaceId"),"followup-0","2026-10-28T03:00:00Z",Map.of("referenceIndex",0,"question","复核哪些任务"));
        assertThat(service.followUp(actor,new A2uiService.Interaction(query.sessionId(),refs,action))).contains("复核哪些任务","统计天数：7");verify(cards,times(2)).resolve(actor,refs);verify(sessions,never()).start(any(),any(),any(),any(),any());
    }
    @Test void deniesForgedActionSourceAndUnregisteredOperationsBeforeBusinessRead(){
        for(String name:List.of("eval","APPROVE","FOLLOW_UP")){
            var action=new A2uiService.Action(name,"forged-surface","followup-0","2026-10-28T03:00:00Z",Map.of("referenceIndex",0,"question","问题"));
            assertThatThrownBy(()->service.followUp(actor,new A2uiService.Interaction("sess_demo",refs,action))).isInstanceOf(IllegalArgumentException.class);
        }verifyNoInteractions(cards);
    }
    @Test void unavailableDataDoesNotProduceInventedMetricsOrInteractiveFollowUps()throws Exception{
        when(cards.resolve(actor,refs)).thenReturn(List.of(new AgentCards.View("METRICS",refs.get(0).tool(),"UNAVAILABLE",List.of(),Map.of(),null,null,null,"当前无权读取",null)));
        String result=json.writeValueAsString(service.resolve(actor,query));assertThat(result).contains("当前无权读取","刷新数据").doesNotContain("Metric","FOLLOW_UP","BarChart");
    }
    @Test void taskViewsExposeOnlySelectedDisplayFieldsAndActualDefectCounts()throws Exception{
        var ref=new AgentCards.Reference("TASKS","get_task_detail",List.of("task-1"),null);var input=new A2uiService.Query("sess_demo",List.of(ref));
        when(cards.resolve(actor,input.cards())).thenReturn(List.of(new AgentCards.View("TASKS",ref.tool(),"OK",List.of(Map.of("taskId","task-1","defectCount",3,"privatePath","SECRET_PATH")),Map.of(),null,null,"OWNED_OR_ASSIGNED","范围内记录",null)));
        assertThat(json.writeValueAsString(service.resolve(actor,input))).contains("DataTable","Tabs","BarChart","task-1","未提供").doesNotContain("SECRET_PATH","privatePath");
    }
}
