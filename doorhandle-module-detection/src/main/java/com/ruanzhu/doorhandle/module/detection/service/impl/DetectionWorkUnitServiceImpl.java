package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitApplyRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitDecisionRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitSubmitRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitDispatchRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitImageBindRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitImageMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionWorkUnitService;
import com.ruanzhu.doorhandle.module.detection.service.DetectionWorkUnitAudit;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.List;
import java.util.ArrayList;
import java.util.Objects;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class DetectionWorkUnitServiceImpl implements DetectionWorkUnitService {
    private final DetectionWorkUnitMapper mapper;
    private final DetectionWorkUnitImageMapper imageMapper;
    private final BusinessUserDirectory users;
    private final DetectionWorkUnitAudit audit;

    @Override @Transactional
    public DetectionWorkUnit apply(DetectionWorkUnitApplyRequest request) {
        var actor = users.authenticated();
        requireApplicantRole(actor);
        String userId = actor.username();
        int count = request.getImageCount() == null ? 5000 : request.getImageCount();
        if (count < 1 || count > 5000) throw new IllegalArgumentException("单个工作单元图片数量必须在 1-5000 之间");
        DetectionWorkUnit unit = new DetectionWorkUnit();
        UUID requestId = request.getRequestId();
        UUID id = requestId == null ? UUID.randomUUID() : UUID.nameUUIDFromBytes((userId + ':' + requestId).getBytes(StandardCharsets.UTF_8));
        unit.setWorkUnitId("WU-" + id.toString().replace("-", ""));
        unit.setApplicantUserId(userId); unit.setImageCount(count); unit.setCompletedCount(0);
        unit.setStrategy("ALL".equalsIgnoreCase(request.getStrategy()) ? "ALL" : "UNDETECTED_ONLY");
        unit.setModelVersion(request.getModelVersion()); unit.setRemark(request.getRemark());
        unit.setStatus("WAITING"); unit.setVersion(0); unit.setCreatedAt(LocalDateTime.now()); unit.setUpdatedAt(LocalDateTime.now());
        if (requestId == null) {
            mapper.insert(unit);
            lockEligibleApplicant(actor);
            audit.record(actor, "DETECTION_APPLICATION_SUBMITTED", unit.getWorkUnitId(), id.toString(), 0);
            return unit;
        }
        mapper.insertApplication(unit);
        var saved = mapper.lock(unit.getWorkUnitId());
        lockEligibleApplicant(actor);
        if (!userId.equals(saved.getApplicantUserId()) || !Objects.equals(unit.getImageCount(), saved.getImageCount())
                || !Objects.equals(unit.getStrategy(), saved.getStrategy()) || !Objects.equals(unit.getModelVersion(), saved.getModelVersion())
                || !Objects.equals(unit.getRemark(), saved.getRemark())) {
            throw new BusinessException(409, "申请编号已用于其他内容，请重新发起申请");
        }
        audit.record(actor, "DETECTION_APPLICATION_SUBMITTED", saved.getWorkUnitId(), requestId.toString(), 0);
        return saved;
    }

    @Override @Transactional
    public DetectionWorkUnit reject(String workUnitId, DetectionWorkUnitDecisionRequest request) {
        return decide(workUnitId, request, "REJECTED");
    }

    @Override @Transactional
    public DetectionWorkUnit withdraw(String workUnitId, DetectionWorkUnitDecisionRequest request) {
        return decide(workUnitId, request, "WITHDRAWN");
    }

    private DetectionWorkUnit decide(String workUnitId, DetectionWorkUnitDecisionRequest request, String status) {
        var actor = users.authenticated();
        boolean employeeWithdrawal = "WITHDRAWN".equals(status);
        if (employeeWithdrawal) requireApplicantRole(actor);
        else requireSupervisor(actor);
        if (request.expectedVersion() == null || request.expectedVersion() < 0 || request.requestId() == null) {
            throw new BusinessException(400, "请核对申请版本和操作编号");
        }
        String reason = request.reason() == null || request.reason().isBlank() ? null : request.reason().strip();
        if (!employeeWithdrawal && reason == null) throw new BusinessException(400, "请输入驳回原因");
        if (reason != null && reason.length() > 1000) throw new BusinessException(400, "原因不能超过1000字");

        var unit = mapper.lock(workUnitId);
        if (unit == null || "OSS_FOLDER".equals(unit.getStrategy())) throw new BusinessException(404, "检测申请不存在");
        // Folder approval and legacy dispatch also lock this row before changing its status.
        if (employeeWithdrawal) {
            if (!actor.username().equals(unit.getApplicantUserId())) {
                throw new BusinessException(403, "只能撤回本人提交的检测申请");
            }
            lockEligibleApplicant(actor);
        } else {
            requireSupervisor(users.lockCurrent(actor.userId(), actor.username()));
        }
        String requestId = request.requestId().toString();
        if (requestId.equals(unit.getDecisionRequestId())) {
            if (status.equals(unit.getStatus()) && Objects.equals(actor.userId(), unit.getDecisionActorUserId())
                    && unit.getVersion() - 1 == request.expectedVersion() && Objects.equals(reason, unit.getDecisionReason())) {
                return unit;
            }
            throw new BusinessException(409, "操作编号已用于其他决定，请刷新申请后核对");
        }
        checkVersion(unit, request.expectedVersion());
        if (!"WAITING".equals(unit.getStatus()) || unit.getAssigneeUserId() != null
                || unit.getSourceBatchId() != null || unit.getBatchId() != null) {
            throw new BusinessException(409, "仅待审批且尚未派单的申请可驳回或撤回");
        }
        unit.setStatus(status);
        unit.setDecisionRequestId(requestId);
        unit.setDecisionActorUserId(actor.userId());
        unit.setDecisionReason(reason);
        unit.setUpdatedAt(LocalDateTime.now());
        if (mapper.recordApplicationDecision(unit, request.expectedVersion()) != 1) {
            throw new BusinessException(409, "检测申请已变化，请刷新后重试");
        }
        unit.setVersion(request.expectedVersion() + 1);
        audit.record(actor, employeeWithdrawal ? "DETECTION_APPLICATION_WITHDRAWN" : "DETECTION_APPLICATION_REJECTED",
                workUnitId, requestId, unit.getVersion());
        return unit;
    }

    private void requireApplicantRole(BusinessUserDirectory.Identity actor) {
        if (actor.supervisor()) throw new BusinessException(403, "仅检测员工可提交或撤回检测申请");
    }

    private void requireSupervisor(BusinessUserDirectory.Identity actor) {
        if (!actor.supervisor()) throw new BusinessException(403, "仅主管可驳回检测申请");
    }

    private void lockEligibleApplicant(BusinessUserDirectory.Identity actor) {
        try {
            users.lockDetectionEmployee(actor.userId(), actor.username());
        } catch (SecurityException denied) {
            throw new BusinessException(403, "当前账号不具备在岗检测员工资格");
        }
    }

    @Override public List<DetectionWorkUnit> listMine(String userId) { return mapper.findMine(userId); }
    @Override public List<DetectionWorkUnit> listActive() { return mapper.findActive(); }

    @Override @Transactional
    public DetectionWorkUnit submit(String workUnitId, DetectionWorkUnitSubmitRequest request, String userId) {
        DetectionWorkUnit unit = find(workUnitId);
        if (userId == null || !userId.equals(unit.getAssigneeUserId())) throw new com.ruanzhu.doorhandle.common.BusinessException(403, "仅当前负责人可提交工作单元");
        if (!List.of("ASSIGNED", "PROCESSING").contains(unit.getStatus())) throw new IllegalStateException("当前工作单元状态不可提交");
        checkVersion(unit, request.getExpectedVersion());
        String oldStatus = unit.getStatus();
        var images = imageMapper.findByWorkUnitId(workUnitId);
        if (images.isEmpty() || images.size() != unit.getImageCount()
                || images.stream().anyMatch(i -> !"SUCCESS".equals(i.getStatus()) && !"FAILED".equals(i.getStatus())))
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "图片尚未全部完成处理，不能提交审核");
        int completed = (int) images.stream().filter(i -> "SUCCESS".equals(i.getStatus())).count();
        unit.setCompletedCount(completed); unit.setRemark(request.getRemark()); unit.setStatus("SUBMITTED"); unit.setSubmittedAt(LocalDateTime.now()); unit.setUpdatedAt(LocalDateTime.now());
        saveTransition(unit, request.getExpectedVersion(), oldStatus); return unit;
    }

    @Override @Transactional
    public DetectionWorkUnit dispatch(String workUnitId, DetectionWorkUnitDispatchRequest request, String operator) {
        DetectionWorkUnit unit = find(workUnitId);
        if (!"WAITING".equals(unit.getStatus())) throw new IllegalStateException("仅待分配工作单元可以派发");
        checkVersion(unit, request.getExpectedVersion());
        unit.setAssigneeUserId(request.getAssigneeUserId()); unit.setStatus("ASSIGNED"); unit.setAssignedAt(LocalDateTime.now());
        unit.setRemark(request.getRemark()); unit.setUpdatedAt(LocalDateTime.now());
        saveTransition(unit, request.getExpectedVersion(), "WAITING"); return unit;
    }

    @Override @Transactional
    public DetectionWorkUnit recall(String workUnitId, Integer expectedVersion, String operator) {
        DetectionWorkUnit unit = find(workUnitId);
        if (!List.of("ASSIGNED", "PROCESSING").contains(unit.getStatus())) throw new IllegalStateException("当前状态不可回收");
        checkVersion(unit, expectedVersion);
        String oldStatus = unit.getStatus();
        unit.setAssigneeUserId(null); unit.setStatus("WAITING"); unit.setAssignedAt(null); unit.setUpdatedAt(LocalDateTime.now());
        saveTransition(unit, expectedVersion, oldStatus); return unit;
    }

    private DetectionWorkUnit find(String workUnitId) {
        DetectionWorkUnit unit = mapper.selectOne(new LambdaQueryWrapper<DetectionWorkUnit>()
                .eq(DetectionWorkUnit::getWorkUnitId, workUnitId).last("FOR UPDATE"));
        if (unit == null || "OSS_FOLDER".equals(unit.getStrategy())) throw new IllegalArgumentException("工作单元不存在");
        if (unit.getBatchId() != null && unit.getBatchId().startsWith("det_folder_")) {
            throw new BusinessException(409, "申请已关联检测任务，请在任务列表处理");
        }
        return unit;
    }
    private void checkVersion(DetectionWorkUnit unit, Integer expectedVersion) {
        if (expectedVersion == null || !expectedVersion.equals(unit.getVersion())) throw new com.ruanzhu.doorhandle.common.BusinessException(409, "工作单元已更新，请刷新后重试");
    }

    private void saveTransition(DetectionWorkUnit unit, Integer version, String status) {
        if (mapper.transition(unit, version, status) != 1)
            throw new com.ruanzhu.doorhandle.common.BusinessException(409, "工作单元已更新，请刷新后重试");
        unit.setVersion(version + 1);
    }

    @Override @Transactional
    public List<DetectionWorkUnitImage> bindImages(String workUnitId, DetectionWorkUnitImageBindRequest request, String operator) {
        DetectionWorkUnit unit = find(workUnitId);
        if (!List.of("WAITING", "ASSIGNED").contains(unit.getStatus())) throw new IllegalStateException("当前状态不可绑定图片");
        if (request.getImages().size() > 5000) throw new IllegalArgumentException("单个工作单元最多 5000 张图片");
        List<DetectionWorkUnitImage> result = new ArrayList<>();
        for (var file : request.getImages()) {
            DetectionWorkUnitImage image = new DetectionWorkUnitImage();
            image.setWorkUnitId(workUnitId); image.setImageId("IMG-" + java.util.UUID.randomUUID().toString().replace("-", ""));
            image.setFileName(file.getFileName()); image.setSha256(file.getSha256()); image.setObjectKey(file.getObjectKey());
            image.setStatus("PENDING"); image.setVersion(0); image.setCreatedAt(LocalDateTime.now()); image.setUpdatedAt(LocalDateTime.now());
            imageMapper.insert(image); result.add(image);
        }
        unit.setImageCount(result.size()); unit.setUpdatedAt(LocalDateTime.now()); mapper.updateById(unit);
        return result;
    }

    @Override public List<DetectionWorkUnitImage> listImages(String workUnitId) { return imageMapper.findByWorkUnitId(workUnitId); }
}
