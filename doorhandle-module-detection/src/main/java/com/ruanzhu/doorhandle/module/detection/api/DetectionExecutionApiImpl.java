package com.ruanzhu.doorhandle.module.detection.api;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionTask;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.security.DetectionTaskAccessPolicy;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
import com.ruanzhu.doorhandle.module.detection.service.detection.DetectionRetryPolicy;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** No HTTP endpoint or direct tool registration: callers must first persist an explicit approval. */
@Service
@ConditionalOnProperty(prefix="detection.commands",name="enabled",havingValue="true")
public class DetectionExecutionApiImpl implements DetectionExecutionApi {
    private final DetectionTaskMapper tasks;
    private final DetectionTaskService service;
    private final DetectionTaskAccessPolicy access;
    private final BusinessUserDirectory users;
    private final OperationsAuditApi audit;
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    public DetectionExecutionApiImpl(DetectionTaskMapper tasks,DetectionTaskService service,DetectionTaskAccessPolicy access,
                                    BusinessUserDirectory users,OperationsAuditApi audit,JdbcTemplate jdbc,ObjectMapper json) {
        this.tasks=tasks;this.service=service;this.access=access;this.users=users;this.audit=audit;this.jdbc=jdbc;this.json=json;
    }
    @PostConstruct public void verifySchema() {
        jdbc.queryForList("SELECT command_id,result_json FROM detection_execution_command WHERE 1=0");
        jdbc.queryForList("SELECT event_id FROM detection_dispatch_outbox WHERE 1=0");
        jdbc.queryForList("SELECT result_sha256 FROM detection_worker_receipt WHERE 1=0");
    }
    @Override public void assertReadable(AgentActor actor,String taskId) {
        actor=current(actor);token(taskId);load(actor,taskId,false);
    }
    @Override public RetryPreview previewRetry(AgentActor actor,String taskId) {
        actor=current(actor);token(taskId);
        var task=load(actor,taskId,false);
        DetectionRetryPolicy.assertEligible(task,json);
        assertPreviousExecutionKnown(task);
        return new RetryPreview(taskId,version(task),task.getStatus(),task.getFlowStatus(),task.getDispatchId(),
                task.getModelId(),task.getThreshold(),imageCount(task),
                "将以相同原图和检测参数创建新的派发，清空当前检测结果与复核、处置状态；不会自动复核、放行或审批报告");
    }
    @Override @Transactional
    public Receipt retry(AgentActor actor,String requestId,String proposalId,RetryApproval approval) {
        if(!TransactionSynchronizationManager.isActualTransactionActive())throw new IllegalStateException("检测命令需要事务");
        actor=current(actor);token(requestId);token(proposalId);
        if(approval==null)throw new IllegalArgumentException("缺少检测批准参数");
        token(approval.taskId());
        if(approval.resourceVersion()==null || !approval.resourceVersion().matches("[0-9a-f]{64}"))throw new IllegalArgumentException("检测批准版本无效");
        var task=load(actor,approval.taskId(),true);
        String fingerprint=hash(encoded(List.of("RETRY",proposalId,approval)));
        var prior=stored(actor,requestId);
        if(prior.isPresent()) {
            if(!fingerprint.equals(prior.get().fingerprint()) || !"RETRY".equals(prior.get().receipt().operation()))
                throw new IllegalArgumentException("请求编号已用于其他检测参数");
            return prior.get().receipt();
        }
        if(!version(task).equals(approval.resourceVersion()))throw new ResourceChanged();
        DetectionRetryPolicy.assertEligible(task,json);
        assertPreviousExecutionKnown(task);
        String previousDispatchId=task.getDispatchId();
        service.retryTaskForAgent(actor,task.getTaskId(),requestId);
        var saved=load(actor,task.getTaskId(),false);
        if(!"QUEUED".equals(saved.getStatus()) || saved.getDispatchId()==null || saved.getDispatchId().equals(previousDispatchId))
            throw new IllegalStateException("新的检测派发未核实");
        var events=jdbc.queryForList("SELECT event_id FROM detection_dispatch_outbox WHERE task_id=? AND dispatch_id=? AND actor_user_id=? AND request_id=?",
                saved.getTaskId(),saved.getDispatchId(),actor.userId(),requestId);
        if(events.size()!=1)throw new IllegalStateException("检测事务消息未保存");
        var result=new Receipt(UUID.randomUUID().toString(),"RETRY",saved.getTaskId(),saved.getDispatchId(),"QUEUED");
        jdbc.update("INSERT INTO detection_execution_command(command_id,actor_user_id,request_id,command_type,payload_sha256,proposal_id,task_id,dispatch_id,result_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))",
                result.commandId(),actor.userId(),requestId,result.operation(),fingerprint,proposalId,result.taskId(),result.dispatchId(),encoded(result));
        audit.append(new OperationsAuditApi.Event(actor,"ENTERPRISE","DETECTION","RETRY_ACCEPTED",result.taskId(),requestId,"APPLIED",null));
        return result;
    }
    @Override public Optional<Receipt> receipt(AgentActor actor,String requestId) {
        actor=current(actor);token(requestId);
        var result=stored(actor,requestId).map(Stored::receipt);
        if(result.isPresent())load(actor,result.get().taskId(),false);
        return result;
    }
    private record Stored(String fingerprint,Receipt receipt) {}
    private Optional<Stored> stored(AgentActor actor,String requestId) {
        var rows=jdbc.query("SELECT payload_sha256,command_id,command_type,task_id,dispatch_id,result_json FROM detection_execution_command WHERE actor_user_id=? AND request_id=?",
                (rs,n)->{
                    try {
                        var receipt=json.readValue(rs.getString("result_json"),Receipt.class);
                        if(!Objects.equals(receipt.commandId(),rs.getString("command_id")) || !Objects.equals(receipt.operation(),rs.getString("command_type"))
                                || !Objects.equals(receipt.taskId(),rs.getString("task_id")) || !Objects.equals(receipt.dispatchId(),rs.getString("dispatch_id"))
                                || !"QUEUED".equals(receipt.status()))throw new IllegalStateException();
                        return new Stored(rs.getString("payload_sha256"),receipt);
                    } catch(Exception error) { throw new IllegalStateException("已保存的检测命令回执不可核实"); }
                },actor.userId(),requestId);
        return rows.stream().findFirst();
    }
    private AgentActor current(AgentActor actor) {
        if(actor==null)throw new SecurityException("缺少认证身份");
        var value=users.current(actor.userId(),actor.username());
        if(value.userId()!=actor.userId() || !value.username().equals(actor.username()) || value.supervisor()!=actor.supervisor())
            throw new SecurityException("账号或角色已变化");
        return actor;
    }
    private DetectionTask load(AgentActor actor,String taskId,boolean lock) {
        var query=new QueryWrapper<DetectionTask>().eq("task_id",taskId);
        access.applyScope(query,actor);
        if(lock)query.last("FOR UPDATE");
        var task=tasks.selectOne(query);
        if(task==null)throw new SecurityException("任务不存在或无访问权限");
        return task;
    }
    private void assertPreviousExecutionKnown(DetectionTask task) {
        if(task.getDispatchId()==null || task.getDispatchId().isBlank())throw new NeedsReview();
        var receipts=jdbc.queryForList("SELECT status,result_json,result_sha256 FROM detection_worker_receipt WHERE task_id=? AND dispatch_id=?",task.getTaskId(),task.getDispatchId());
        if(receipts.isEmpty()) {
            Integer events=jdbc.queryForObject("SELECT COUNT(*) FROM detection_dispatch_outbox WHERE task_id=? AND dispatch_id=?",Integer.class,task.getTaskId(),task.getDispatchId());
            // Legacy completed business results can be explicitly rechecked. An
            // unexplained failure or a dispatched command without a receipt cannot.
            if(events==null || events!=0 || !Set.of("COMPLETED","PARTIAL_FAILED").contains(task.getStatus())
                    || task.getLastFinishedEventId()==null || task.getFinishedAt()==null)throw new NeedsReview();
            return;
        }
        var receipt=receipts.get(0);
        if(!"COMPLETED".equals(receipt.get("status")) || !(receipt.get("result_json") instanceof String result)
                || !hash(result).equals(receipt.get("result_sha256")))throw new NeedsReview();
        try {
            var resultTree=json.readTree(result);
            if(!task.getTaskId().equals(resultTree.path("taskId").asText()) || !task.getDispatchId().equals(resultTree.path("dispatchId").asText())
                    || !task.getStatus().equals(resultTree.path("status").asText()) || !"DETECTION_TASK_FINISHED".equals(resultTree.path("eventType").asText()))
                throw new NeedsReview();
        } catch(Exception invalid) { throw new NeedsReview(); }
    }
    private int imageCount(DetectionTask task) {
        try { return json.readTree(task.getOriginalImageKeysJson()).size(); }
        catch(Exception error) { throw new IllegalStateException("原图数量不可核实"); }
    }
    private String version(DetectionTask task) { return hash(encoded(task)); }
    private String encoded(Object value) {
        try { return json.writeValueAsString(value); }
        catch(Exception error) { throw new IllegalStateException("检测快照不可生成"); }
    }
    private static void token(String value) {
        if(value==null || !value.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("检测编号无效");
    }
    private static String hash(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch(Exception error) { throw new IllegalStateException("检测摘要不可生成"); }
    }
}
