package com.ruanzhu.doorhandle.module.detection.security;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DetectionTaskAccessPolicyTest {

    private final DetectionTaskAccessPolicy policy = new DetectionTaskAccessPolicy();

    @Test
    void employeeCannotAccessForeignTask() {
        DetectionTask task = taskOwnedBy("alice");
        var auth = authentication("bob", "ROLE_OPERATOR");

        assertThatThrownBy(() -> policy.assertCanAccess(task, auth))
                .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
    }

    @Test
    void ownerCanAccessTask() {
        policy.assertCanAccess(taskOwnedBy("alice"), authentication("alice", "ROLE_OPERATOR"));
    }

    @Test
    void assignedEmployeeAndSupervisorCanAccessTask() {
        DetectionTask task = taskOwnedBy("alice");
        task.setAssignee("bob");
        policy.assertCanAccess(task, authentication("bob", "ROLE_INSPECTOR"));
        policy.assertCanAccess(task, authentication("boss", "ROLE_SUPERVISOR"));
        task.setAssignee("charlie");
        assertThatThrownBy(() -> policy.assertCanAccess(task, authentication("bob", "ROLE_INSPECTOR")))
                .isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
    }

    @Test
    void anonymousAuthenticationTokenIsNotAnAuthenticatedUser() {
        var anonymous = new org.springframework.security.authentication.AnonymousAuthenticationToken(
                "key", "anonymousUser", List.of(new SimpleGrantedAuthority("ROLE_ANONYMOUS")));
        assertThatThrownBy(() -> policy.assertCanAccess(taskOwnedBy("alice"), anonymous))
                .isInstanceOf(BusinessException.class);
    }

    @Test
    void adminCanAccessForeignTask() {
        policy.assertCanAccess(taskOwnedBy("alice"), authentication("root", "ROLE_ADMIN"));
    }

    @Test
    void anonymousCannotAccessTask() {
        assertThatThrownBy(() -> policy.assertCanAccess(taskOwnedBy("alice"), null))
                .isInstanceOf(BusinessException.class)
                .hasMessage("请先登录");
    }

    private DetectionTask taskOwnedBy(String username) {
        DetectionTask task = new DetectionTask();
        task.setCreatedBy(username);
        return task;
    }

    private UsernamePasswordAuthenticationToken authentication(String username, String authority) {
        return new UsernamePasswordAuthenticationToken(
                username, "n/a", List.of(new SimpleGrantedAuthority(authority)));
    }
}
