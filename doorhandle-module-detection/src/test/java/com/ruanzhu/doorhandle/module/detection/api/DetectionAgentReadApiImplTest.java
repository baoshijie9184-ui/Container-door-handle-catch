package com.ruanzhu.doorhandle.module.detection.api;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
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
        assertThatThrownBy(() -> api.task(employee, "foreign-task")).isInstanceOf(SecurityException.class);
        verify(mapper).selectOne(captor.capture());
        assertThat(captor.getValue().getSqlSegment()).contains("created_by", "assignee", "task_id");
        assertThat(captor.getValue().getParamNameValuePairs()).containsValues("alice", "foreign-task");
    }
    @Test void taskResponseDoesNotExposeStorageKeysOrSession() {
        DetectionTask task = new DetectionTask();
        task.setTaskId("task-1"); task.setSourceOssPrefix("private/key"); task.setSessionId("private-session");
        when(mapper.selectOne(any())).thenReturn(task);
        assertThat(api.task(employee, "task-1").toString()).doesNotContain("private/key", "private-session");
    }
    @Test void invalidInputsDoNotReachMapper() {
        assertThatThrownBy(() -> api.tasks(employee, 1, 101, false)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> api.task(employee, "' OR 1=1")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> api.metrics(employee, 0)).isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(mapper);
    }
}
