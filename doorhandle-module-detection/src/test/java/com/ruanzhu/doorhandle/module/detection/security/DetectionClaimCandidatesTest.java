package com.ruanzhu.doorhandle.module.detection.security;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class DetectionClaimCandidatesTest {
    @Test void canonicalAccountIdsRetainLongPrecisionAndUseNumericOrder(){
        assertThat(DetectionClaimCandidates.canonical(List.of("9223372036854775807","2","10"))).containsExactly("2","10","9223372036854775807");
        assertThat(DetectionClaimCandidates.encode(List.of())).isNull();
        assertThat(DetectionClaimCandidates.read("[\"10\",\"2\"]")).containsExactly("2","10");
    }
    @Test void inputAndPersistedShapesFailClosed(){
        for(var value:List.of(List.of("0"),List.of("01"),List.of("-1"),List.of("9223372036854775808"),List.of("1","1"),java.util.stream.LongStream.rangeClosed(1,17).mapToObj(Long::toString).toList()))
            assertThatThrownBy(()->DetectionClaimCandidates.canonical(value)).isInstanceOf(IllegalArgumentException.class);
        for(String raw:List.of("[1]","null","{}","[\"01\"]"))assertThatThrownBy(()->DetectionClaimCandidates.read(raw)).isInstanceOf(IllegalStateException.class);
    }
    @Test void explicitCandidateOnlyReadsVacantReviewTaskAndNeverAcquiresMutationPermission(){
        var directory=mock(BusinessUserDirectory.class);when(directory.current(2,"candidate")).thenReturn(new BusinessUserDirectory.Identity(2,"candidate",false));
        var policy=new DetectionTaskAccessPolicy();policy.setUsers(directory);ReflectionTestUtils.setField(policy,"candidateReadsEnabled",true);
        var task=new DetectionTask();task.setTaskId("task");task.setCreatedBy("owner");task.setStatus("COMPLETED");task.setFlowStatus("PENDING_REVIEW");task.setClaimCandidateIds("[\"2\"]");
        var actor=new AgentActor(2,"candidate",AgentActor.Role.INSPECTOR);
        assertThat(policy.canAccess(task,actor)).isTrue();assertThat(policy.canMutate(task,actor)).isFalse();assertThatThrownBy(()->policy.assertCanMutate(task,actor)).isInstanceOf(SecurityException.class);
        task.setAssignee("winner");assertThat(policy.canAccess(task,actor)).isFalse();task.setAssignee(null);task.setFlowStatus("REVIEWING");assertThat(policy.canAccess(task,actor)).isFalse();
        task.setFlowStatus("PENDING_REVIEW");task.setClaimCandidateIds(null);assertThat(policy.canAccess(task,actor)).isFalse();
    }
    @Test void disabledFeatureAndFreshQualificationNeverTrustStoredCandidateId(){
        var directory=mock(BusinessUserDirectory.class);when(directory.current(2,"candidate")).thenReturn(new BusinessUserDirectory.Identity(2,"candidate",false));
        var policy=new DetectionTaskAccessPolicy();policy.setUsers(directory);var task=new DetectionTask();task.setCreatedBy("owner");task.setStatus("COMPLETED");task.setFlowStatus("PENDING_REVIEW");task.setClaimCandidateIds("[\"2\"]");var actor=new AgentActor(2,"candidate",AgentActor.Role.INSPECTOR);
        assertThat(policy.canAccess(task,actor)).isFalse();ReflectionTestUtils.setField(policy,"candidateReadsEnabled",true);
        when(directory.current(2,"candidate")).thenThrow(new SecurityException("qualification revoked"));assertThatThrownBy(()->policy.canAccess(task,actor)).isInstanceOf(SecurityException.class);
    }
}
