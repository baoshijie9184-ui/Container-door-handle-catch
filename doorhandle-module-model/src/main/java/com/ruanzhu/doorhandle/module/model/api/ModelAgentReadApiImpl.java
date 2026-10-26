package com.ruanzhu.doorhandle.module.model.api;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.agent.ModelAgentReadApi;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import org.springframework.stereotype.Service;
import java.util.List;
import java.util.ArrayList;
import java.util.Set;
import java.math.BigDecimal;
import java.time.LocalDateTime;

@Service
public class ModelAgentReadApiImpl implements ModelAgentReadApi {
    private final ModelInfoMapper mapper;
    public ModelAgentReadApiImpl(ModelInfoMapper mapper) { this.mapper = mapper; }

    @Override
    public List<ModelView> models(AgentActor actor, int page, int size) {
        actor.requireSupervisor();
        if (page < 1 || page > 10000 || size < 1 || size > 100) throw new IllegalArgumentException("分页参数超出范围");
        return mapper.selectList(new LambdaQueryWrapper<ModelInfo>().orderByAsc(ModelInfo::getModelId)
                        .last("LIMIT " + size + " OFFSET " + ((page - 1) * size)))
                .stream().map(this::view).toList();
    }

    @Override
    public ModelView model(AgentActor actor, int modelId) {
        actor.requireSupervisor();
        if (modelId < 1) throw new IllegalArgumentException("模型 ID 不合法");
        ModelInfo model = mapper.selectById(modelId);
        if (model == null) throw new BusinessException(404, "模型不存在");
        return view(model);
    }

    private ModelView view(ModelInfo m) {
        return new ModelView(m.getModelId(), m.getModelName(), m.getVersion(), m.getStatus(), m.getIsDefault());
    }

    @Override
    public Operations operations(AgentActor actor, int modelId) {
        actor.requireSupervisor();
        if (modelId < 1) throw new IllegalArgumentException("模型 ID 不合法");
        // 显式列裁剪，不读取文件路径、校验文案、兼容性说明或操作者信息。
        var m = mapper.selectOne(new LambdaQueryWrapper<ModelInfo>().select(ModelInfo::getModelId, ModelInfo::getModelName,
                ModelInfo::getVersion, ModelInfo::getStatus, ModelInfo::getIsDefault, ModelInfo::getValidationStatus,
                ModelInfo::getMlopsStatus, ModelInfo::getEvaluationDataset, ModelInfo::getPrecisionScore, ModelInfo::getRecallScore,
                ModelInfo::getMapScore, ModelInfo::getF1Score, ModelInfo::getAvgInferenceMs, ModelInfo::getDeploymentStrategy,
                ModelInfo::getTrainingImageCount, ModelInfo::getTrainingCompletedAt, ModelInfo::getEvaluationImageCount,
                ModelInfo::getNoDetectionImageCount, ModelInfo::getInferenceFps,
                ModelInfo::getCanaryPercent, ModelInfo::getAbGroup, ModelInfo::getRollbackFromModelId,
                ModelInfo::getUsageCount, ModelInfo::getLastUsedAt, ModelInfo::getPublishedAt).eq(ModelInfo::getModelId,modelId));
        if (m == null) throw new BusinessException(404, "模型不存在");
        var invalid = new ArrayList<String>();
        var evaluation = new Evaluation(m.getEvaluationDataset(), score(m.getPrecisionScore(),"precisionScore",invalid),
                score(m.getRecallScore(),"recallScore",invalid), score(m.getMapScore(),"mapScore",invalid),
                score(m.getF1Score(),"f1Score",invalid), integer(m.getAvgInferenceMs(),0,Integer.MAX_VALUE,"avgInferenceMs",invalid),
                integer(m.getTrainingImageCount(),1,Integer.MAX_VALUE,"trainingImageCount",invalid), m.getTrainingCompletedAt(),
                integer(m.getEvaluationImageCount(),0,Integer.MAX_VALUE,"evaluationImageCount",invalid),
                integer(m.getNoDetectionImageCount(),0,Integer.MAX_VALUE,"noDetectionImageCount",invalid),
                fps(m.getInferenceFps(),invalid));
        if (m.getNoDetectionImageCount() != null && m.getEvaluationImageCount() != null
                && m.getNoDetectionImageCount() > m.getEvaluationImageCount()) invalid.add("noDetectionImageCount");
        var rollout = new Rollout(code(m.getDeploymentStrategy(),Set.of("FULL","CANARY","AB_TEST","ROLLBACK"),"strategy",invalid),
                integer(m.getCanaryPercent(),0,100,"configuredPercent",invalid), m.getAbGroup(),
                integer(m.getRollbackFromModelId(),1,Integer.MAX_VALUE,"rollbackFromModelId",invalid));
        var usage = new Usage(integer(m.getUsageCount(),0,Integer.MAX_VALUE,"usageCount",invalid),m.getLastUsedAt(),m.getPublishedAt());
        String validation = code(m.getValidationStatus(),Set.of("PASSED","FAILED","PENDING"),"validationStatus",invalid);
        String mlops = code(m.getMlopsStatus(),Set.of("UNASSESSED","EVALUATED","ROLLOUT","ROLLED_BACK"),"mlopsStatus",invalid);
        return new Operations(view(m), validation, mlops, evaluation, rollout, usage, LocalDateTime.now(), invalid);
    }

    private BigDecimal score(BigDecimal value,String field,List<String> invalid) {
        if (value == null || value.compareTo(BigDecimal.ZERO)>=0 && value.compareTo(BigDecimal.ONE)<=0) return value;
        invalid.add(field); return null;
    }
    private BigDecimal fps(BigDecimal value,List<String> invalid) {
        if (value == null || value.signum() > 0 && value.compareTo(new BigDecimal("99999999.9999")) <= 0) return value;
        invalid.add("inferenceFps"); return null;
    }
    private Integer integer(Integer value,int minimum,int maximum,String field,List<String> invalid) {
        if (value == null || value>=minimum && value<=maximum) return value;
        invalid.add(field); return null;
    }
    private String code(String value,Set<String> allowed,String field,List<String> invalid) {
        if (value == null || allowed.contains(value)) return value;
        invalid.add(field); return null;
    }
}
