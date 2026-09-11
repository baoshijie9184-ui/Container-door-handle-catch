# ONNX 模型治理与可追溯选型

> 返回总览：[项目亮点与面试指南](../项目亮点与面试指南.md)

## 1. 章节目标

本章讲解 ONNX 模型从上传、校验、评估、发布到归档的生命周期，以及任务如何记录模型版本。灰度配置与真实任务选型的边界会单独说明。

### 1.1 术语、字段与状态翻译

| 英文术语、字段或状态 | 中文名称 | 含义 |
| --- | --- | --- |
| ONNX | 开放神经网络交换格式 | 让不同训练框架导出的模型能够在统一推理环境中运行 |
| modelCode | 模型编码 | 模型在系统中的稳定业务标识 |
| version / modelVersion | 版本 / 模型版本 | 标识模型迭代版本，并写入检测任务用于追溯 |
| OSS Key | 对象存储键 | 模型文件在对象存储中的唯一位置 |
| DRAFT | 草稿 | 模型已经上传，但尚未通过可用性校验 |
| READY | 就绪 | 模型校验通过，可以进行发布 |
| PUBLISHED | 已发布 | 模型可以被检测任务选择使用 |
| DISABLED | 已停用 | 模型暂时不能用于新任务 |
| ARCHIVED | 已归档 | 模型退出使用，但历史记录继续保留 |
| is_default | 是否默认 | 标识未指定版本时优先选择的模型 |
| threshold | 置信度阈值 | 低于该值的检测结果不作为有效缺陷 |
| deployment_strategy | 部署策略 | 保存默认、灰度等模型使用策略元数据 |

## 2. 生命周期图

~~~text
管理员上传 ONNX 模型文件与版本信息
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤一：创建模型记录                                        │
│                                                              │
│  状态：草稿（DRAFT）                                         │
│  保存模型编码、版本、对象存储位置、指标和创建人              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤二：ONNX 模型可用性校验                                 │
│                                                              │
│  校验文件格式、输入输出节点、模型加载和基础推理              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                       校验通过？
                           │
                    ┌──────┴──────┐
                    │             │
                   否             是
                    │             │
                    ▼             ▼
            保持草稿并记录错误     状态更新为就绪
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────┐
│  步骤三：发布与默认版本管理                                  │
│                                                              │
│  就绪（READY）→ 已发布（PUBLISHED）                          │
│  可将已发布版本设置为默认模型                                │
│  新任务记录实际使用的模型版本，保证结果可追溯                │
└──────────────────────────┬───────────────────────────────────┘
                           │
                      模型后续操作
                           │
                    ┌──────┴──────┐
                    │             │
                   停用           归档
                    │             │
                    ▼             ▼
                已停用           已归档
                    │             │
                    └──────┬──────┘
                           ▼
              历史检测任务仍保留原模型版本引用
~~~

## 3. 数据关系

~~~mermaid
erDiagram
    MODEL_MANAGEMENT ||--o{ MODEL_OPERATION_LOG : records
    MODEL_MANAGEMENT ||--o{ DETECTION_TASK : selected_by

    MODEL_MANAGEMENT {
        int model_id PK
        varchar model_name
        varchar version
        varchar status
        boolean is_default
        varchar validation_status
        varchar deployment_strategy
    }
    MODEL_OPERATION_LOG {
        bigint id PK
        int model_id FK
        varchar operation_type
        varchar operator
        datetime operation_time
    }
    DETECTION_TASK {
        varchar task_id UK
        int model_id
        varchar model_version
        decimal threshold
    }
~~~

## 4. 核心字段

| 字段 | 说明 |
| --- | --- |
| model_id | 模型主键 |
| model_name、version | 唯一版本标识 |
| model_path | ONNX 文件路径 |
| status | 模型状态：草稿、就绪、已发布、已停用、已归档 |
| is_default | 默认模型标识 |
| validation_status、validation_message | 加载校验结果 |
| precision_score、recall_score | 精确率与召回率 |
| map_score、f1_score | 综合评估指标 |
| avg_inference_ms | 平均推理耗时 |
| usage_count、last_used_at | 使用统计 |
| deployment_strategy | FULL、CANARY、AB_TEST、ROLLBACK |
| canary_percent、ab_group | 灰度和 A/B 元数据 |
| rollback_from_model_id | 回滚来源 |

## 5. 核心代码

### 5.1 ONNX 校验

~~~java
ValidationResult result = modelValidationService.validate(
        Path.of(modelInfo.getModelPath()));
modelInfo.setValidationStatus(result.status());
modelInfo.setValidationMessage(result.message());
if ("PASSED".equals(result.status())) {
    if (!"PUBLISHED".equals(modelInfo.getStatus())) {
        modelInfo.setStatus("READY");
    }
} else {
    modelInfo.setStatus("DRAFT");
    modelInfo.setIsDefault(false);
}
~~~

校验失败的模型不能发布，也不能继续作为默认模型。

### 5.2 发布与默认模型

~~~java
if (!"PASSED".equals(modelInfo.getValidationStatus())) {
    throw new BusinessException("模型校验未通过，不能发布");
}
modelInfo.setStatus("PUBLISHED");

clearDefaultFlag();
modelInfo.setIsDefault(true);
~~~

设置新默认模型前先清理其他模型的默认标记，避免多个默认版本。

### 5.3 当前任务选型

~~~java
if (modelId != null) {
    return modelInfoMapper.selectByModelId(modelId);
}
return allModels.stream()
        .filter(model -> Boolean.TRUE.equals(model.getIsDefault()))
        .findFirst()
        .orElseGet(() -> allModels.stream()
                .filter(model -> "PUBLISHED".equals(model.getStatus()))
                .findFirst()
                .orElse(allModels.get(0)));
~~~

选择顺序：显式 modelId → 默认模型 → 第一个已发布模型 → 第一个模型。

任务创建后把 model_id、model_version、threshold 写入 detection_task，后续默认模型发生变化也不会改变历史任务的模型快照。

### 5.4 评估与灰度元数据

~~~java
existing.setPrecisionScore(evaluation.getPrecisionScore());
existing.setRecallScore(evaluation.getRecallScore());
existing.setMapScore(evaluation.getMapScore());
existing.setF1Score(evaluation.getF1Score());
existing.setAvgInferenceMs(evaluation.getAvgInferenceMs());

existing.setDeploymentStrategy(normalizedStrategy);
existing.setCanaryPercent(safePercent);
existing.setAbGroup(abGroup);
existing.setRollbackFromModelId(rollbackFromModelId);
~~~

## 6. 真实能力边界

| 能力 | 状态 |
| --- | --- |
| ONNX 文件加载校验 | 已实现 |
| 版本唯一性与生命周期 | 已实现 |
| 模型评估指标记录 | 已实现 |
| 默认模型选择 | 已实现 |
| 灰度、A/B、回滚配置保存 | 已实现 |
| 按灰度比例自动选择任务模型 | 尚未实现 |
| 按 A/B 分组自动路由 | 尚未实现 |

后续可对 userId、deviceId 或 batchNo 做一致性哈希，稳定地把同一对象路由到同一模型版本。

## 7. 测试与面试问答

主要测试：ModelServiceImplTest、ModelInfoServiceImplTest、OnnxModelValidationService 相关测试。

### 为什么任务表还要保存 model_version？

model_id 能关联当前模型记录，但版本文本快照更方便历史报告直接展示，也避免模型元数据被修改后难以解释旧结果。

### 如何描述灰度能力才准确？

系统已具备灰度策略元数据和配置校验，但任务选型仍使用默认模型逻辑；自动分流属于后续演进。
