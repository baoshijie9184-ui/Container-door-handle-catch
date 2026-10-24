package com.ruanzhu.doorhandle.module.detection.api;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskAssignmentRequest;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
import com.ruanzhu.doorhandle.module.detection.service.detection.DetectionQualityWorkflow;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.time.LocalDateTime;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;

/** 复用业务分配规则；确认事务先锁任务并比较完整资源快照，再执行业务更新。 */
@Service
public class DetectionAssignmentApiImpl implements DetectionAssignmentApi {
    private final DetectionTaskMapper tasks;
    private final DetectionTaskService service;
    private final AgentUserDirectory users;
    private final ObjectMapper json;
    @org.springframework.beans.factory.annotation.Value("${detection.assignment-writes-enabled:true}") private boolean assignmentWrites=true;
    private org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService> identities;
    @org.springframework.beans.factory.annotation.Autowired
    public void setIdentities(org.springframework.beans.factory.ObjectProvider<com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService> identities){this.identities=identities;}
    @org.springframework.beans.factory.annotation.Value("${detection.identity.assignment-binding-enabled:false}") private boolean assignmentBinding;
    @jakarta.annotation.PostConstruct public void requireIdentity(){if(assignmentBinding&&(identities==null||identities.getIfAvailable()==null||!identities.getObject().assignmentBindingEnabled()))throw new IllegalStateException("分派身份登记需要先启用 V40 稳定身份服务并迁移 V54");}
    public DetectionAssignmentApiImpl(DetectionTaskMapper tasks, DetectionTaskService service, AgentUserDirectory users, ObjectMapper json) {
        this.tasks=tasks; this.service=service; this.users=users; this.json=json;
    }
    @Transactional(noRollbackFor={ResourceChanged.class,SecurityException.class,IllegalArgumentException.class})
    public Preview preview(AgentActor actor, Command command) {
        requireWritable();
        users.assertSupervisor(actor);
        validate(command);
        var task = load(command.taskId(), true);
        eligible(task);
        var assignee=users.inspector(command.assignee().trim());
        checkIdentity(command,assignee,false);
        var due = command.dueAt() == null || command.dueAt().isBlank() ? task.getDueAt() : parseDue(command.dueAt());
        var normalized = new Command(command.taskId(), command.qualityStation().trim(), command.assignee().trim(),
                due == null ? null : due.toString(), command.assignmentRemark() == null ? "" : command.assignmentRemark().trim(),assignee.userId(),assignee.revision());
        return new Preview(normalized, values(task), version(task,assignee));
    }
    @Transactional(noRollbackFor={ResourceChanged.class,SecurityException.class,IllegalArgumentException.class})
    public Applied apply(AgentActor actor, Command command, String expectedResourceVersion) {
        requireWritable();
        users.assertSupervisor(actor);
        validate(command);
        if (!TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("分配必须在数据库事务内执行");
        var task = load(command.taskId(), true);
        var assignee=users.inspector(command.assignee());checkIdentity(command,assignee,true);
        users.lockInspector(assignee);
        if (!version(task,assignee).equals(expectedResourceVersion)) throw new ResourceChanged();
        eligible(task);
        String expectedFlow = DetectionQualityWorkflow.assignedFlow(task);
        var request = new DetectionTaskAssignmentRequest();
        request.setQualityStation(command.qualityStation()); request.setAssignee(command.assignee());
        request.setAssigneeUserId(assignee.userId());request.setAssigneeRevision(assignee.revision());
        var assignment=identity(task);request.setExpectedAssignmentRevision(assignment==null?null:assignment.revision());
        // 现有业务服务使用 OffsetDateTime 解析，适配本地业务时间而不改变日期数字。
        request.setDueAt(command.dueAt()==null?null:parseDue(command.dueAt()).atOffset(java.time.ZoneOffset.ofHours(8)).toString());
        request.setAssignmentRemark(command.assignmentRemark());
        service.assignQualityTask(command.taskId(), request);
        var saved = load(command.taskId(), false);
        var expectedDue = command.dueAt() == null ? null : parseDue(command.dueAt());
        if (!java.util.Objects.equals(saved.getQualityStation(),command.qualityStation())
                || !java.util.Objects.equals(saved.getAssignee(),command.assignee())
                || !java.util.Objects.equals(saved.getDueAt(),expectedDue)
                || !java.util.Objects.equals(saved.getAssignmentRemark(),command.assignmentRemark())
                || !java.util.Objects.equals(saved.getFlowStatus(),expectedFlow))
            throw new IllegalStateException("分配结果核验失败");
        var value=values(saved);
        if(value.assigneeUserId()!=null&&!value.assigneeUserId().equals(assignee.userId()))throw new IllegalStateException("分派责任人身份回执不一致");
        if(value.assignedByUserId()!=null&&!value.assignedByUserId().equals(actor.userId()))throw new IllegalStateException("分派操作人身份回执不一致");
        return new Applied(command.taskId(),new Values(value.qualityStation(),value.assignee(),value.dueAt(),value.assignmentRemark(),value.flowStatus(),assignee.userId(),actor.userId(),actor.username(),value.assignmentRevision()));
    }
    private DetectionTask load(String id, boolean lock) {
        var query = new QueryWrapper<DetectionTask>().eq("task_id", id);
        if (lock) query.last("FOR UPDATE");
        var task = tasks.selectOne(query);
        if (task == null) throw new IllegalArgumentException("任务不存在");
        return task;
    }
    private static void eligible(DetectionTask task) {
        try {
            DetectionQualityWorkflow.assertAssignable(task);
        } catch (com.ruanzhu.doorhandle.common.BusinessException error) {
            // Keep the contracts facade's existing validation failure semantics.
            throw new IllegalArgumentException(error.getMessage(), error);
        }
    }
    private static void validate(Command c) {
        if (c == null || c.taskId() == null || !c.taskId().matches("[A-Za-z0-9_-]{1,128}")
                || c.qualityStation() == null || c.qualityStation().isBlank() || c.qualityStation().length()>64
                || c.assignee() == null || !c.assignee().trim().matches("[A-Za-z0-9_.-]{1,50}")
                || (c.assignmentRemark()!=null && c.assignmentRemark().length()>500)) throw new IllegalArgumentException("分配参数不正确");
        if (c.dueAt()!=null && !c.dueAt().isBlank()) parseDue(c.dueAt());
    }
    private static LocalDateTime parseDue(String value) {
        try { var date=LocalDateTime.parse(value.replace(' ','T')); if (date.getNano()!=0) throw new IllegalArgumentException(); return date; }
        catch (RuntimeException error) { throw new IllegalArgumentException("截止时间必须是秒精度的本地日期时间"); }
    }
    private String version(DetectionTask task,AgentUserDirectory.Inspector assignee) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writeValueAsString(java.util.Arrays.asList("assignment-v3-preserve-stage",task,assignee,identity(task))).getBytes(StandardCharsets.UTF_8))); }
        catch (Exception error) { throw new IllegalStateException("资源快照生成失败"); }
    }
    private Values values(DetectionTask t) {
        var identity=identity(t);
        return new Values(t.getQualityStation(),t.getAssignee(),t.getDueAt()==null?null:t.getDueAt().toString(),t.getAssignmentRemark(),t.getFlowStatus(),identity==null?null:identity.assigneeUserId(),identity==null?null:identity.assignedByUserId(),identity==null?null:identity.assignedByName(),identity==null?null:identity.revision());
    }
    private com.ruanzhu.doorhandle.module.detection.service.DetectionIdentityService.AssignmentIdentity identity(DetectionTask task){
        var value=identities==null?null:identities.getIfAvailable();return value==null?null:value.assignmentIdentity(task.getTaskId());
    }
    private void checkIdentity(Command command,AgentUserDirectory.Inspector target,boolean required){
        boolean present=command.assigneeUserId()!=null||command.assigneeRevision()!=null;
        if(required&&!present || present&&(!java.util.Objects.equals(command.assigneeUserId(),target.userId())||!java.util.Objects.equals(command.assigneeRevision(),target.revision())))throw new ResourceChanged();
    }
    private void requireWritable(){if(!assignmentWrites)throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE,"当前兼容模式暂停质检分派，可继续查询历史、拒绝或取消提议");}
}
