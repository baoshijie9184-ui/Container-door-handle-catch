package com.ruanzhu.doorhandle.module.detection.api;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionTaskAssignmentRequest;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
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
    public DetectionAssignmentApiImpl(DetectionTaskMapper tasks, DetectionTaskService service, AgentUserDirectory users, ObjectMapper json) {
        this.tasks=tasks; this.service=service; this.users=users; this.json=json;
    }
    public Preview preview(AgentActor actor, Command command) {
        users.assertSupervisor(actor);
        validate(command);
        var task = load(command.taskId(), false);
        eligible(task);
        if (!users.inspectorExists(command.assignee().trim())) throw new IllegalArgumentException("责任人必须是现有员工账号");
        var due = command.dueAt() == null || command.dueAt().isBlank() ? task.getDueAt() : parseDue(command.dueAt());
        var normalized = new Command(command.taskId(), command.qualityStation().trim(), command.assignee().trim(),
                due == null ? null : due.toString(), command.assignmentRemark() == null ? "" : command.assignmentRemark().trim());
        return new Preview(normalized, values(task), version(task));
    }
    @Transactional(noRollbackFor={ResourceChanged.class,SecurityException.class,IllegalArgumentException.class})
    public Applied apply(AgentActor actor, Command command, String expectedResourceVersion) {
        users.assertSupervisor(actor);
        validate(command);
        if (!TransactionSynchronizationManager.isActualTransactionActive()) throw new IllegalStateException("分配必须在数据库事务内执行");
        var task = load(command.taskId(), true);
        if (!version(task).equals(expectedResourceVersion)) throw new ResourceChanged();
        eligible(task);
        if (!users.inspectorExists(command.assignee())) throw new IllegalArgumentException("责任人员工账号已失效");
        String expectedFlow="REWORK_REQUIRED".equals(task.getFlowStatus())?"REWORK_REQUIRED":"REVIEWING";
        var request = new DetectionTaskAssignmentRequest();
        request.setQualityStation(command.qualityStation()); request.setAssignee(command.assignee());
        // 现有业务服务使用 OffsetDateTime 解析，适配本地业务时间而不改变日期数字。
        request.setDueAt(command.dueAt()==null?null:parseDue(command.dueAt()).atZone(java.time.ZoneId.systemDefault()).toOffsetDateTime().toString());
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
        return new Applied(command.taskId(), values(saved));
    }
    private DetectionTask load(String id, boolean lock) {
        var query = new QueryWrapper<DetectionTask>().eq("task_id", id);
        if (lock) query.last("FOR UPDATE");
        var task = tasks.selectOne(query);
        if (task == null) throw new IllegalArgumentException("任务不存在");
        return task;
    }
    private static void eligible(DetectionTask task) {
        if (!("COMPLETED".equals(task.getStatus()) || "PARTIAL_FAILED".equals(task.getStatus())))
            throw new IllegalArgumentException("只有已完成检测任务才能分配质检");
        if (java.util.Set.of("RELEASED","SCRAPPED","ARCHIVED").contains(java.util.Objects.toString(task.getFlowStatus(),"")))
            throw new IllegalArgumentException("已关闭任务不能重新分配质检");
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
    private String version(DetectionTask task) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writeValueAsString(task).getBytes(StandardCharsets.UTF_8))); }
        catch (Exception error) { throw new IllegalStateException("资源快照生成失败"); }
    }
    private static Values values(DetectionTask t) { return new Values(t.getQualityStation(), t.getAssignee(),
            t.getDueAt()==null?null:t.getDueAt().toString(),t.getAssignmentRemark(),t.getFlowStatus()); }
}
