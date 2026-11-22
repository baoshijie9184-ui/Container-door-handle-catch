package com.ruanzhu.doorhandle.module.detection.api;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import java.lang.reflect.RecordComponent;
import java.util.Arrays;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class DetectionAgentReadApiImplTest {
    private final DetectionTaskMapper mapper = mock(DetectionTaskMapper.class);
    private final DetectionAgentReadApiImpl api = new DetectionAgentReadApiImpl(mapper);
    private final AgentActor employee = new AgentActor(1, "alice", AgentActor.Role.INSPECTOR);

    @Test void employeeListAndDetailBothEnforceOwnedOrAssignedInSql() {
        when(mapper.selectCount(any())).thenReturn(0L);
        when(mapper.selectList(any(QueryWrapper.class))).thenReturn(List.of());
        api.tasks(employee, 1, 20, false);
        var captor = ArgumentCaptor.forClass(QueryWrapper.class);
        verify(mapper).selectList(captor.capture());
        assertThat(captor.getValue().getSqlSegment()).contains("(created_by", " OR assignee");
        assertThat(captor.getValue().getParamNameValuePairs()).containsValue("alice");
        assertThat(captor.getValue().getSqlSelect().split(",")).containsExactlyInAnyOrder(
                "task_id", "status", "flow_status", "device_name", "total_images", "processed_images",
                "defect_count", "review_status", "review_conclusion", "created_at");
        assertThatThrownBy(() -> api.task(employee, "foreign-task")).isInstanceOf(SecurityException.class);
        verify(mapper).selectOne(captor.capture());
        assertThat(captor.getValue().getSqlSegment()).contains("created_by", "assignee", "task_id");
        assertThat(captor.getValue().getParamNameValuePairs()).containsValues("alice", "foreign-task");
        assertThat(captor.getValue().getSqlSelect()).contains("task_id", "review_status")
                .doesNotContain("source_oss_prefix", "defect_evidence_json", "session_id", "review_remark");
    }
    @Test void workloadIncludesOnlyFormalTasksInTheEmployeesScope() {
        when(mapper.selectMaps(any())).thenReturn(List.of());
        api.metrics(employee, 30);
        var query = ArgumentCaptor.forClass(QueryWrapper.class);
        verify(mapper).selectMaps(query.capture());
        assertThat(query.getValue().getSqlSegment()).contains("created_by", "assignee",
                "task_type IS NULL OR task_type <> 'SINGLE'", "created_at");
    }

    @Test void taskResponseDoesNotExposeStorageKeysOrSession() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("task-1"); task.setSourceOssPrefix("private/key"); task.setSessionId("private-session");
        task.setReviewRemark("private-review-note"); task.setDefectEvidenceJson("private-evidence");
        when(mapper.selectOne(any())).thenReturn(task);
        var view = api.task(employee, "task-1");
        assertThat(view.taskId()).isEqualTo("task-1");
        assertThat(view.toString()).doesNotContain("private/key", "private-session", "private-review-note", "private-evidence");
        assertThat(Arrays.stream(view.getClass().getRecordComponents()).map(RecordComponent::getName).toList())
                .containsExactlyInAnyOrder("taskId", "status", "flowStatus", "deviceName", "totalImages",
                        "processedImages", "defectCount", "reviewStatus", "reviewConclusion", "createdAt");
    }

    @Test void staleSupervisorReadsInCurrentScopeIncludingLiveFolderAssignment() {
        var users = mock(BusinessUserDirectory.class);
        var identities = mock(DetectionIdentityService.class);
        when(users.current(1, "alice")).thenReturn(new BusinessUserDirectory.Identity(1, "alice", false));
        when(identities.active()).thenReturn(true);
        when(identities.predicate("", "{0}")).thenReturn("(created_user_id={0} OR assignee_user_id={0})");
        var policy = new DetectionTaskAccessPolicy();
        policy.setUsers(users);
        policy.setIdentities(identities);
        ReflectionTestUtils.setField(policy, "folderAssignments", mock(JdbcTemplate.class));
        var readApi = new DetectionAgentReadApiImpl(mapper, policy);
        var previousSupervisor = new AgentActor(1, "alice", AgentActor.Role.SUPERVISOR);

        assertThatThrownBy(() -> readApi.task(previousSupervisor, "folder-other"))
                .isInstanceOf(SecurityException.class);
        var query = ArgumentCaptor.forClass(QueryWrapper.class);
        verify(mapper).selectOne(query.capture());
        assertThat(query.getValue().getSqlSegment()).contains("created_user_id", "assignee_user_id",
                "detection_task.task_type = 'OSS_FOLDER'", "w.assignee_user_id", "task_id =");
        assertThat(query.getValue().getParamNameValuePairs()).containsValues(1L, "folder-other");

        when(mapper.selectMaps(any())).thenReturn(List.of());
        assertThat(readApi.metrics(previousSupervisor, 7).scope()).isEqualTo("OWNED_OR_ASSIGNED");

        var mutation = new QueryWrapper<DetectionTask>();
        policy.applyScope(mutation, previousSupervisor);
        assertThat(mutation.getSqlSegment()).doesNotContain("detection_work_unit");
    }
    @Test void invalidInputsDoNotReachMapper() {
        assertThatThrownBy(() -> api.tasks(employee, 1, 101, false)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> api.task(employee, "' OR 1=1")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> api.metrics(employee, 0)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(mapper);
    }
}
