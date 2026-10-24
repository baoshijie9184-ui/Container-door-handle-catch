package com.ruanzhu.doorhandle.module.model.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.BusinessMutation;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.entity.ModelOperationLog;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import com.ruanzhu.doorhandle.module.model.mapper.ModelOperationLogMapper;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;

/** Separate proxy boundary: register only after bounded upload and validation have finished. */
@Service
public class ModelRegistrationService {
    /** Raised only by a failed INSERT, never by commit, audit, or an ambiguous network response. */
    public static class IdentifierCollision extends RuntimeException {
        IdentifierCollision(org.springframework.dao.DuplicateKeyException failure) { super(failure); }
    }
    private final ModelInfoMapper models;
    private final ModelOperationLogMapper logs;
    private final ModelMutationIdentity identity;
    private final ObjectProvider<ModelFileJournal> journals;
    public ModelRegistrationService(ModelInfoMapper models, ModelOperationLogMapper logs,
                                    ModelMutationIdentity identity,ObjectProvider<ModelFileJournal> journals) {
        this.models=models;this.logs=logs;this.identity=identity;this.journals=journals;
    }
    @Transactional(rollbackFor=Exception.class)
    @org.springframework.cache.annotation.CacheEvict(cacheNames={"model","dashboard"},allEntries=true)
    @BusinessMutation(domain="DETECTION_MODEL",action="UPLOAD",resource="result.modelId",request="arg0.requestId",supervisorOnly=true)
    public ModelInfo register(ModelUploadFiles.Prepared file,String name,String version,String description,
                              ModelValidationService.ValidationResult validation) {
        var actor=identity.supervisor();
        if(actor.userId()!=file.actorUserId()) throw new SecurityException("模型上传账号已变化");
        if(models.selectByModelNameAndVersion(name,version)!=null) throw new BusinessException("模型名称和版本已存在");
        var model=new ModelInfo();
        model.setModelId(models.selectNextModelId());model.setModelName(name);model.setVersion(version);
        model.setModelPath(file.path().toString());model.setUploadTime(LocalDateTime.now());
        model.setUpdateDescription(description);model.setStatus("PASSED".equals(validation.status())?"READY":"DRAFT");
        model.setIsDefault(false);model.setCreator(actor.username());model.setUsageCount(0);
        model.setValidationStatus(validation.status());model.setValidationMessage(validation.message());
        model.setMlopsStatus("UNASSESSED");model.setDeploymentStrategy("FULL");model.setCanaryPercent(100);
        try {
            if(models.insert(model)!=1) throw new BusinessException("模型信息未登记");
        } catch(org.springframework.dao.DuplicateKeyException duplicate) { throw new IdentifierCollision(duplicate); }
        var journal=journals.getIfAvailable();
        if(journal!=null) journal.registered(file,model.getModelId());
        var log=new ModelOperationLog();log.setModelId(model.getModelId());log.setOperationType("UPLOAD");
        log.setOperator(actor.username());log.setOperationTime(LocalDateTime.now());
        log.setRemark("上传模型，校验结果: "+validation.status());
        if(logs.insert(log)!=1) throw new IllegalStateException("模型操作审计未保存");
        return model;
    }
}
