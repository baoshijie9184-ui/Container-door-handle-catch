package com.ruanzhu.doorhandle.module.detection.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentUserDirectory;
import com.ruanzhu.doorhandle.contracts.agent.BusinessMutation;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskProgressResponse;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class DetectionTaskClaimService {
    public record Claim(String expectedVersion, String requestId) { }
    private final DetectionTaskMapper tasks;
    private final DetectionTaskService views;
    private final DetectionTaskAccessPolicy policy;
    private final BusinessUserDirectory users;
    private final AgentUserDirectory inspectors;
    private final JdbcTemplate jdbc;
    private final ObjectProvider<DetectionIdentityService> identities;
    public DetectionTaskClaimService(DetectionTaskMapper tasks, DetectionTaskService views, DetectionTaskAccessPolicy policy,
            BusinessUserDirectory users, AgentUserDirectory inspectors, JdbcTemplate jdbc, ObjectProvider<DetectionIdentityService> identities) {
        this.tasks=tasks;this.views=views;this.policy=policy;this.users=users;this.inspectors=inspectors;this.jdbc=jdbc;this.identities=identities;
    }
    @Transactional(rollbackFor=Exception.class)
    @BusinessMutation(domain="DETECTION",action="claimTask")
    public DetectionTaskProgressResponse claim(String taskId, Claim command) {
        var actor=users.authenticated();
        if(actor.supervisor())throw new BusinessException(403,"请由检测人员本人领取任务，主管可使用分派功能");
        if(command==null||command.expectedVersion()==null||!command.expectedVersion().matches("0|[1-9][0-9]{0,18}"))throw new BusinessException(400,"缺少任务版本");
        var inspector=inspectors.lockInspector(inspectors.inspector(actor.username()));
        var task=tasks.selectOne(new LambdaQueryWrapper<DetectionTask>().eq(DetectionTask::getTaskId,taskId).last("FOR UPDATE"));
        policy.assertCanAccess(task, org.springframework.security.core.context.SecurityContextHolder.getContext().getAuthentication());
        if(task==null||task.getVersion()==null||!task.getVersion().toString().equals(command.expectedVersion()))throw new BusinessException(409,"任务版本已变化，请刷新后重试");
        // Claim only inside the caller's existing task scope; it does not grant access to an enterprise-wide pool.
        int changed=jdbc.update("UPDATE detection_task SET assignee=?,flow_status='REVIEWING',assigned_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE task_id=? AND version=? AND (assignee IS NULL OR TRIM(assignee)='') AND status IN ('COMPLETED','PARTIAL_FAILED') AND flow_status='PENDING_REVIEW'",
                actor.username(),taskId,task.getVersion());
        if(changed!=1)throw new BusinessException(409,"任务已被领取或当前状态不允许领取");
        task.setAssignee(actor.username());
        var identity=identities.getIfAvailable();
        if(identity!=null)identity.recordClaim(task,inspector);
        return views.getTaskProgress(taskId);
    }
}
