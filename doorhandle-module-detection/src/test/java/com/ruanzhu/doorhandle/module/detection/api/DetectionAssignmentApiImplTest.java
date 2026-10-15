package com.ruanzhu.doorhandle.module.detection.api;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
import org.junit.jupiter.api.*;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.time.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
class DetectionAssignmentApiImplTest {
    private final AgentActor boss=new AgentActor(1,"boss",AgentActor.Role.SUPERVISOR);
    private DetectionTaskMapper mapper;private DetectionTaskService service;private AgentUserDirectory users;private DetectionAssignmentApiImpl api;private DetectionTask task;
    private final DetectionAssignmentApi.Command command=new DetectionAssignmentApi.Command("task-1","站点A","alice","2026-11-01T15:30:00","确认分配");
    @BeforeEach void setup() {
        mapper=mock(DetectionTaskMapper.class);service=mock(DetectionTaskService.class);users=mock(AgentUserDirectory.class);
        api=new DetectionAssignmentApiImpl(mapper,service,users,new ObjectMapper().findAndRegisterModules());
        task=new DetectionTask();task.setTaskId("task-1");task.setStatus("COMPLETED");task.setFlowStatus("DETECTED");task.setDueAt(LocalDateTime.of(2026,10,30,15,0));
        when(mapper.selectOne(any())).thenReturn(task);when(users.inspectorExists("alice")).thenReturn(true);
    }
    @AfterEach void cleanup(){TransactionSynchronizationManager.setActualTransactionActive(false);}
    @Test void previewsPreserveExistingDeadlineAndNeverCallBusinessWrite(){
        var view=api.preview(boss,new DetectionAssignmentApi.Command("task-1"," 站点A ","alice",null,null));
        assertThat(view.command().qualityStation()).isEqualTo("站点A");assertThat(view.command().dueAt()).isEqualTo("2026-10-30T15:00");verifyNoInteractions(service);
    }
    @Test void locksTaskRechecksSnapshotAndVerifiesRealSavedFields(){
        var preview=api.preview(boss,command);TransactionSynchronizationManager.setActualTransactionActive(true);
        when(service.assignQualityTask(anyString(),any())).thenAnswer(inv->{var request=(com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskAssignmentRequest)inv.getArgument(1);
            task.setAssignee(request.getAssignee());task.setQualityStation(request.getQualityStation());task.setDueAt(OffsetDateTime.parse(request.getDueAt()).toLocalDateTime());task.setAssignmentRemark(request.getAssignmentRemark());task.setFlowStatus("REVIEWING");return null;});
        assertThat(api.apply(boss,preview.command(),preview.resourceVersion()).after().dueAt()).isEqualTo("2026-11-01T15:30");
        verify(mapper,atLeastOnce()).selectOne(argThat(query->query.getSqlSegment().contains("FOR UPDATE")));
    }
    @Test void changedResourceAndClosedTaskNeverReachBusinessService(){
        var preview=api.preview(boss,command);task.setFlowStatus("ARCHIVED");TransactionSynchronizationManager.setActualTransactionActive(true);
        assertThatThrownBy(()->api.apply(boss,preview.command(),preview.resourceVersion())).isInstanceOf(DetectionAssignmentApi.ResourceChanged.class);
        assertThatThrownBy(()->api.preview(boss,command)).isInstanceOf(IllegalArgumentException.class);verifyNoInteractions(service);
    }
    @Test void badParametersOrMissingEmployeeFailBeforeAnyBusinessWrite(){
        assertThatThrownBy(()->api.preview(boss,new DetectionAssignmentApi.Command("../task","站点","alice",null,null))).isInstanceOf(IllegalArgumentException.class);
        when(users.inspectorExists("alice")).thenReturn(false);assertThatThrownBy(()->api.preview(boss,command)).isInstanceOf(IllegalArgumentException.class);verifyNoInteractions(service);
    }
}
