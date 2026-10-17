package com.ruanzhu.doorhandle.contracts.agent;

import java.util.List;
import java.math.BigDecimal;
import java.time.LocalDateTime;

public interface ModelAgentReadApi {
    record ModelView(Integer modelId, String name, String version, String status, Boolean defaultModel) {}
    List<ModelView> models(AgentActor actor, int page, int size);
    ModelView model(AgentActor actor, int modelId);
    record Evaluation(String dataset, BigDecimal precisionScore, BigDecimal recallScore, BigDecimal mapScore,
                      BigDecimal f1Score, Integer avgInferenceMs) {}
    /** 数据库配置，不表示执行链已按此分流。 */
    record Rollout(String strategy, Integer configuredPercent, String abGroup, Integer rollbackFromModelId) {}
    record Usage(Integer count, LocalDateTime lastUsedAt, LocalDateTime publishedAt) {}
    record Operations(ModelView model, String validationStatus, String mlopsStatus, Evaluation evaluation,
                      Rollout rollout, Usage usage, LocalDateTime queriedAt, List<String> invalidFields) {
        public Operations { invalidFields = List.copyOf(invalidFields); }
    }
    Operations operations(AgentActor actor, int modelId);
}
