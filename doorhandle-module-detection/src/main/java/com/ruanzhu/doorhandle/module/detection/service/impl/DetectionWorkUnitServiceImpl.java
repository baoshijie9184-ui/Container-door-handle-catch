package com.ruanzhu.doorhandle.module.detection.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitApplyRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitSubmitRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitDispatchRequest;
import com.ruanzhu.doorhandle.module.detection.dto.detection.DetectionWorkUnitImageBindRequest;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitImageMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnit;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionWorkUnitMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionWorkUnitService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.List;
import java.util.ArrayList;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class DetectionWorkUnitServiceImpl implements DetectionWorkUnitService {
    private final DetectionWorkUnitMapper mapper;
    private final DetectionWorkUnitImageMapper imageMapper;

    @Override @Transactional
    public DetectionWorkUnit apply(DetectionWorkUnitApplyRequest request, String userId) {
        int count = request.getImageCount() == null ? 5000 : request.getImageCount();
        if (count < 1 || count > 5000) throw new IllegalArgumentException("单个工作单元图片数量必须在 1-5000 之间");
        DetectionWorkUnit unit = new DetectionWorkUnit();
        unit.setWorkUnitId("WU-" + UUID.randomUUID().toString().replace("-", ""));
        unit.setApplicantUserId(userId); unit.setImageCount(count); unit.setCompletedCount(0);
        unit.setStrategy("ALL".equalsIgnoreCase(request.getStrategy()) ? "ALL" : "UNDETECTED_ONLY");
        unit.setModelVersion(request.getModelVersion()); unit.setRemark(request.getRemark());
        unit.setStatus("WAITING"); unit.setVersion(0); unit.setCreatedAt(LocalDateTime.now()); unit.setUpdatedAt(LocalDateTime.now());
        mapper.insert(unit); return unit;
    }

    @Override public List<DetectionWorkUnit> listMine(String userId) { return mapper.findMine(userId); }
    @Override public List<DetectionWorkUnit> listActive() { return mapper.findActive(); }

    @Override @Transactional
    public DetectionWorkUnit submit(String workUnitId, DetectionWorkUnitSubmitRequest request, String userId) {
        DetectionWorkUnit unit = mapper.selectOne(new LambdaQueryWrapper<DetectionWorkUnit>().eq(DetectionWorkUnit::getWorkUnitId, workUnitId));
        if (unit == null) throw new IllegalArgumentException("工作单元不存在");
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
        DetectionWorkUnit unit = mapper.selectOne(new LambdaQueryWrapper<DetectionWorkUnit>().eq(DetectionWorkUnit::getWorkUnitId, workUnitId));
        if (unit == null) throw new IllegalArgumentException("工作单元不存在");
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
