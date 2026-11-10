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
    public record Candidates(java.util.List<String> candidateUserIds, String expectedVersion, String requestId) { }
    private final DetectionTaskMapper tasks;
    private final DetectionTaskService views;
    private final DetectionTaskAccessPolicy policy;
    private final BusinessUserDirectory users;
    private final AgentUserDirectory inspectors;
    private final JdbcTemplate jdbc;
    private final ObjectProvider<DetectionIdentityService> identities;
    private com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi accounts;
    @org.springframework.beans.factory.annotation.Autowired
    public void accounts(com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi value){accounts=value;}
    @org.springframework.beans.factory.annotation.Value("${collaboration.mutations.enabled:false}") private boolean candidatesEnabled;
    @jakarta.annotation.PostConstruct public void candidateSchema(){if(candidatesEnabled)jdbc.queryForList("SELECT claim_candidate_ids FROM detection_task WHERE 1=0");}
    public DetectionTaskClaimService(DetectionTaskMapper tasks, DetectionTaskService views, DetectionTaskAccessPolicy policy,
            BusinessUserDirectory users, AgentUserDirectory inspectors, JdbcTemplate jdbc, ObjectProvider<DetectionIdentityService> identities) {
        this.tasks=tasks;this.views=views;this.policy=policy;this.users=users;this.inspectors=inspectors;this.jdbc=jdbc;this.identities=identities;
    }
    @Transactional(rollbackFor=Exception.class)
    @BusinessMutation(domain="DETECTION",action="claimTask",request="arg1.requestId")
    public DetectionTaskProgressResponse claim(String taskId, Claim command) {
        var actor=users.authenticated();
        if(actor.supervisor())throw new BusinessException(403,"请由检测人员本人领取任务，主管可使用分派功能");
        if(command==null||command.expectedVersion()==null||!command.expectedVersion().matches("0|[1-9][0-9]{0,18}"))throw new BusinessException(400,"缺少任务版本");
        var inspector=inspectors.lockInspector(inspectors.inspector(actor.username()));
        var task=tasks.selectOne(new LambdaQueryWrapper<DetectionTask>().eq(DetectionTask::getTaskId,taskId).last("FOR UPDATE"));
        policy.assertCanAccess(task, org.springframework.security.core.context.SecurityContextHolder.getContext().getAuthentication());
        if(task==null||task.getVersion()==null||!task.getVersion().toString().equals(command.expectedVersion()))throw new BusinessException(409,"任务版本已变化，请刷新后重试");
        if(candidatesEnabled&&!com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.includes(task,actor.userId()))throw new BusinessException(403,"当前账号不在主管授权的领取候选中");
        int changed=jdbc.update("UPDATE detection_task SET assignee=?,claim_candidate_ids=NULL,flow_status='REVIEWING',assigned_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE task_id=? AND version=? AND (assignee IS NULL OR TRIM(assignee)='') AND status IN ('COMPLETED','PARTIAL_FAILED') AND flow_status='PENDING_REVIEW'",
                actor.username(),taskId,task.getVersion());
        if(changed!=1)throw new BusinessException(409,"任务已被领取或当前状态不允许领取");
        task.setAssignee(actor.username());
        var identity=identities.getIfAvailable();
        if(identity!=null)identity.recordClaim(task,inspector);
        return views.getTaskProgress(taskId);
    }
    @Transactional(rollbackFor=Exception.class)
    @BusinessMutation(domain="DETECTION",action="authorizeClaimCandidates",request="arg1.requestId",supervisorOnly=true)
    public DetectionTaskProgressResponse authorize(String taskId,Candidates command){
        if(!candidatesEnabled)throw new BusinessException(503,"受控领取尚未启用");
        var actor=users.authenticated();if(!actor.supervisor())throw new BusinessException(403,"仅主管可以授权领取候选");
        if(command==null)throw new BusinessException(400,"缺少候选授权参数");
        final java.util.List<String> ids;
        try{ids=com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.canonical(command.candidateUserIds());}
        catch(IllegalArgumentException invalid){throw new BusinessException(400,invalid.getMessage());}
        var task=tasks.selectOne(new LambdaQueryWrapper<DetectionTask>().eq(DetectionTask::getTaskId,taskId).last("FOR UPDATE"));
        if(!com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.vacant(task))throw new BusinessException(409,"仅无人负责且待复核的已完成任务可以授权领取");
        if(command.expectedVersion()==null||task.getVersion()==null||!task.getVersion().toString().equals(command.expectedVersion()))throw new BusinessException(409,"任务版本已变化，请刷新后重试");
        for(String id:ids){
            long userId=Long.parseLong(id);String username=accounts.username(userId);
            if(username==null)throw new BusinessException(400,"候选必须是当前合格的检测账号");
            var target=users.lockCurrent(userId,username);
            if(target.supervisor())throw new BusinessException(400,"候选必须是当前合格的检测账号");
            var inspector=inspectors.lockInspector(inspectors.inspector(username));
            if(inspector.userId()!=userId)throw new BusinessException(409,"候选账号身份已变化，请重新选择");
        }
        String encoded=com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.encode(ids);
        if(!java.util.Objects.equals(com.ruanzhu.doorhandle.module.detection.security.DetectionClaimCandidates.read(task.getClaimCandidateIds()),ids)){
            if(jdbc.update("UPDATE detection_task SET claim_candidate_ids=?,updated_at=CURRENT_TIMESTAMP WHERE task_id=? AND version=?",encoded,taskId,task.getVersion())!=1)throw new BusinessException(409,"任务版本已变化，请刷新后重试");
        }
        return views.getTaskProgress(taskId);
    }
}
