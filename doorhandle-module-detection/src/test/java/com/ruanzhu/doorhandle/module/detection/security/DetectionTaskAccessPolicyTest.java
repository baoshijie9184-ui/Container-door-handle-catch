package com.ruanzhu.doorhandle.module.detection.security;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DetectionTaskAccessPolicyTest {
    @Test void stableAuthorizationRechecksSupervisorRevocationForHttpAndAgentQueries(){
        var identities=org.mockito.Mockito.mock(com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService.class);
        var fresh=new com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory.Identity(7,"boss",false);
        org.mockito.Mockito.when(identities.current(7,"boss")).thenReturn(fresh);
        org.mockito.Mockito.when(identities.current("boss")).thenReturn(fresh);
        org.mockito.Mockito.when(identities.active()).thenReturn(true);
        org.mockito.Mockito.when(identities.predicate("","{0}")).thenReturn("(created_user_id={0} OR (assignee_user_id={0} AND assignee_identity_name=assignee))");
        var policy=new DetectionTaskAccessPolicy();policy.setIdentities(identities);
        var authorities=List.of(new SimpleGrantedAuthority("ROLE_SUPERVISOR"));
        var principal=new com.ruanzhu.doorhandle.module.system.security.TenantPrincipal(7L,"boss","",authorities);
        var auth=new UsernamePasswordAuthenticationToken(principal,null,authorities);
        assertThat(policy.isAdmin(auth)).isFalse();
        assertThatThrownBy(()->policy.assertCanAccess(taskOwnedBy("alice"),auth)).isInstanceOf(org.springframework.security.access.AccessDeniedException.class);
        var query=new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<DetectionTask>();
        policy.applyScope(query,new com.ruanzhu.doorhandle.contracts.agent.AgentActor(7,"boss",com.ruanzhu.doorhandle.contracts.agent.AgentActor.Role.SUPERVISOR));
        assertThat(query.getSqlSegment()).contains("created_user_id","assignee_user_id");assertThat(query.getParamNameValuePairs()).containsValue(7L);
    }

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
