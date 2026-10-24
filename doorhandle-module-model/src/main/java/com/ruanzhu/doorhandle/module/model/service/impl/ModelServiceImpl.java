package com.ruanzhu.doorhandle.module.model.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.model.mapper.ModelOperationLogMapper;
import com.ruanzhu.doorhandle.module.model.service.ModelService;
import com.ruanzhu.doorhandle.module.model.service.ModelValidationService;
import com.ruanzhu.doorhandle.module.model.service.ModelUploadFiles;
import com.ruanzhu.doorhandle.module.model.service.ModelRegistrationService;
import com.ruanzhu.doorhandle.module.model.service.ModelFileJournal;
import org.springframework.beans.factory.ObjectProvider;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;

@Service
@RequiredArgsConstructor
@Slf4j
public class ModelServiceImpl implements ModelService {

    private final ModelInfoMapper modelInfoMapper;
    private final ModelOperationLogMapper modelOperationLogMapper;
    private final ModelValidationService modelValidationService;
    private final ModelUploadFiles uploadFiles;
    private final ModelRegistrationService registration;
    private final ObjectProvider<ModelFileJournal> fileJournals;
    private final com.ruanzhu.doorhandle.module.model.service.ModelMutationIdentity identity;

    @Value("${model.max-upload-bytes:209715200}")
    private long maxUploadBytes;

    @Override
    public ModelInfo uploadModel(MultipartFile file, String modelName, String version, String updateDescription) {
        if (file == null || file.isEmpty()) {
            throw new BusinessException("上传文件不能为空");
        }
        validateOnnxFile(file);
        if(modelName==null || modelName.isBlank() || modelName.length()>100 || version==null || version.isBlank() || version.length()>20
                || (updateDescription!=null && updateDescription.length()>500)) throw new BusinessException("模型名称、版本或说明长度无效");

        ModelInfo existingModel = modelInfoMapper.selectByModelNameAndVersion(modelName, version);
        if (existingModel != null) {
            throw new BusinessException("模型名称和版本已存在");
        }

        var prepared=uploadFiles.write(file);
        var validation=modelValidationService.validate(prepared.path());
        uploadFiles.verify(prepared);
        // Registration is a separate proxied SQL transaction; uncertainty must not trigger byte deletion.
        for(int attempt=0;attempt<3;attempt++) {
            try { return registration.register(prepared,modelName,version,updateDescription,validation); }
            catch(ModelRegistrationService.IdentifierCollision collision) {
                // This INSERT is known to have rolled back; the next proxy call obtains a fresh transaction.
                // Upload bytes and validation are not replayed. Commit/audit/connection errors are not retried.
                if(attempt==2) throw new BusinessException("模型编号冲突，文件保留待核对");
            }
        }
        throw new IllegalStateException("模型登记未完成");
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="updateModel",supervisorOnly=true)
    public ModelInfo updateModel(ModelInfo modelInfo) {
        LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(ModelInfo::getModelId, modelInfo.getModelId());
        ModelInfo existingModel = modelInfoMapper.selectOne(queryWrapper);

        if (existingModel == null) {
            throw new BusinessException("要更新的模型不存在");
        }

        existingModel.setUpdateDescription(modelInfo.getUpdateDescription());

        modelInfoMapper.updateModelRecord(existingModel);
        return existingModel;
    }

    @Override
    @org.springframework.transaction.annotation.Transactional(rollbackFor=Exception.class)
    @org.springframework.cache.annotation.CacheEvict(cacheNames={"model","dashboard"},allEntries=true)
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="deleteModel",supervisorOnly=true)
    public void deleteModel(Integer modelId) {
        identity.supervisor();
        LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(ModelInfo::getModelId, modelId);
        queryWrapper.last("FOR UPDATE");

        ModelInfo modelInfo = modelInfoMapper.selectOne(queryWrapper);
        if (modelInfo == null) {
            throw new BusinessException("要删除的模型不存在");
        }
        if (defaultInt(modelInfo.getUsageCount()) > 0) {
            throw new BusinessException("已被任务引用的模型不允许删除，请改为停用或归档");
        }

        var journal=fileJournals.getIfAvailable();
        if(journal!=null) journal.retain(modelInfo);
        if(modelInfoMapper.deleteByModelId(modelId)!=1) throw new BusinessException("模型记录已变化");
        // File retention is intentional even with the journal disabled. SQL rollback cannot restore bytes.
        // model_operation_log has a foreign key to the deleted row. Durable deletion evidence belongs
        // to the independent retention journal and operations audit, not an INSERT after parent deletion.
    }

    @Override
    public List<ModelInfo> getAllModels() {
        return modelInfoMapper.selectAll();
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="publishModel",supervisorOnly=true)
    public ModelInfo publishModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        if ("ARCHIVED".equals(modelInfo.getStatus())) {
            throw new BusinessException("已归档模型不能直接发布");
        }
        if (!"PASSED".equals(modelInfo.getValidationStatus())) {
            throw new BusinessException("模型校验未通过，不能发布");
        }
        if (!"READY".equals(modelInfo.getStatus()) && !"PUBLISHED".equals(modelInfo.getStatus())) {
            throw new BusinessException("只有就绪模型才能发布");
        }
        modelInfo.setStatus("PUBLISHED");
        if (modelInfo.getPublishedAt() == null) {
            modelInfo.setPublishedAt(LocalDateTime.now());
        }
        saveModel(modelInfo);
        recordOperation(modelId, "PUBLISH", "发布模型");
        return modelInfo;
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="setDefaultModel",supervisorOnly=true)
    public ModelInfo setDefaultModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        if (!"PUBLISHED".equals(modelInfo.getStatus())) {
            throw new BusinessException("只有已发布模型才能设为默认");
        }

        clearDefaultFlag();
        modelInfo.setIsDefault(Boolean.TRUE);
        saveModel(modelInfo);
        recordOperation(modelId, "SET_DEFAULT", "设为默认模型");
        return modelInfo;
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="DISABLE",supervisorOnly=true)
    public ModelInfo disableModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        modelInfo.setStatus("DISABLED");
        modelInfo.setIsDefault(Boolean.FALSE);
        saveModel(modelInfo);
        recordOperation(modelId, "DISABLE", "停用模型");
        return modelInfo;
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="ARCHIVE",supervisorOnly=true)
    public ModelInfo archiveModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        modelInfo.setStatus("ARCHIVED");
        modelInfo.setIsDefault(Boolean.FALSE);
        saveModel(modelInfo);
        recordOperation(modelId, "ARCHIVE", "归档模型");
        return modelInfo;
    }

    @Override
    @com.ruanzhu.doorhandle.contracts.agent.BusinessMutation(domain="DETECTION_MODEL",action="VALIDATE",supervisorOnly=true)
    public ModelInfo validateModel(Integer modelId) {
        ModelInfo modelInfo = requireModel(modelId);
        if (!StringUtils.hasText(modelInfo.getModelPath())) {
            throw new BusinessException("模型文件路径为空，不能校验");
        }

        ModelValidationService.ValidationResult validationResult = modelValidationService.validate(Path.of(modelInfo.getModelPath()));
        modelInfo.setValidationStatus(validationResult.status());
        modelInfo.setValidationMessage(validationResult.message());
        if ("PASSED".equals(validationResult.status())) {
            if (!"PUBLISHED".equals(modelInfo.getStatus())) {
                modelInfo.setStatus("READY");
            }
        } else {
            modelInfo.setStatus("DRAFT");
            modelInfo.setIsDefault(Boolean.FALSE);
        }
        saveModel(modelInfo);
        recordOperation(modelId, "VALIDATE", "重新校验模型，结果: " + validationResult.status());
        return modelInfo;
    }

    @Override
    public void incrementUsageStats(Integer modelId, LocalDateTime usedAt) {
        if (modelId == null) {
            return;
        }
        ModelInfo modelInfo = requireModel(modelId);
        modelInfo.setUsageCount(defaultInt(modelInfo.getUsageCount()) + 1);
        modelInfo.setLastUsedAt(usedAt != null ? usedAt : LocalDateTime.now());
        saveModel(modelInfo);
    }

    @Override
    public List<ModelOperationLog> getOperationLogs(Integer modelId) {
        return modelOperationLogMapper.selectByModelId(modelId);
    }

    private void validateOnnxFile(MultipartFile file) {
        String originalFilename = file.getOriginalFilename();
        if (originalFilename == null || !originalFilename.toLowerCase(Locale.ROOT).endsWith(".onnx")) {
            throw new BusinessException("仅支持上传 ONNX 格式文件");
        }
        if (file.getSize() > maxUploadBytes) {
            throw new BusinessException("模型文件不能超过 " + formatBytes(maxUploadBytes));
        }
    }

    private String formatBytes(long bytes) {
        if (bytes >= 1024L * 1024L) {
            return (bytes / 1024L / 1024L) + "MB";
        }
        if (bytes >= 1024L) {
            return (bytes / 1024L) + "KB";
        }
        return bytes + "B";
    }

    private ModelInfo requireModel(Integer modelId) {
        LambdaQueryWrapper<ModelInfo> queryWrapper = new LambdaQueryWrapper<>();
        queryWrapper.eq(ModelInfo::getModelId, modelId);
        ModelInfo modelInfo = modelInfoMapper.selectOne(queryWrapper);
        if (modelInfo == null) {
            throw new BusinessException("模型不存在");
        }
        return modelInfo;
    }

    private void clearDefaultFlag() {
        List<ModelInfo> models = modelInfoMapper.selectAll();
        if (models == null) {
            return;
        }
        for (ModelInfo existing : models) {
            if (Boolean.TRUE.equals(existing.getIsDefault())) {
                existing.setIsDefault(Boolean.FALSE);
                saveModel(existing);
            }
        }
    }

    private void saveModel(ModelInfo modelInfo) {
        modelInfoMapper.updateModelRecord(modelInfo);
    }

    private void recordOperation(Integer modelId, String operationType, String remark) {
        if (modelId == null) {
            return;
        }
        ModelOperationLog logEntry = new ModelOperationLog();
        logEntry.setModelId(modelId);
        logEntry.setOperationType(operationType);
        logEntry.setOperator(resolveCurrentUsername());
        logEntry.setOperationTime(LocalDateTime.now());
        logEntry.setRemark(remark);
        if(modelOperationLogMapper.insert(logEntry)!=1) throw new IllegalStateException("模型操作日志未保存");
    }

    private String resolveCurrentUsername() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !StringUtils.hasText(authentication.getName())) {
            return "system";
        }
        return authentication.getName();
    }

    private int defaultInt(Integer value) {
        return value == null ? 0 : value;
    }
}
