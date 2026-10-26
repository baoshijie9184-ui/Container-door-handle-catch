<template>
  <section class="detection-model-details" aria-label="检测模型资料">
    <header class="detection-model-heading">
      <span class="detection-model-symbol"><AppIcon name="Tickets" :size="25" /></span>
      <div><h3>{{ model.modelName || '模型名称未记录' }}</h3><p>版本 {{ model.version || '未记录' }} · 模型 ID {{ model.modelId ?? '未记录' }}</p></div>
      <StatusBadge domain="model" :code="model.status" />
    </header>
    <p class="model-next-step">{{ modelNextStep(model) }}</p>

    <section class="model-detail-group">
      <h4><AppIcon name="DocumentChecked" :size="17" />基础校验</h4>
      <StatusBadge domain="modelValidation" :code="model.validationStatus" />
      <div :key="model.validationMessage" class="model-detail-copy" :class="{'is-long':longText(model.validationMessage)}" :tabindex="longText(model.validationMessage) ? 0 : undefined" :role="longText(model.validationMessage) ? 'region' : undefined" :aria-label="longText(model.validationMessage) ? '基础校验完整说明，可使用方向键滚动' : undefined"><p>{{ model.validationMessage || '尚无已记录的校验说明。' }}</p></div>
      <p v-if="longText(model.validationMessage)" class="model-detail-reading-hint"><AppIcon name="Rank" :size="13" />完整校验说明可在上方区域内滚动阅读</p>
      <p class="model-detail-note">基础校验不等同检测效果评估，也不代表质检任务已通过。</p>
    </section>

    <section class="model-detail-group">
      <h4><AppIcon name="DataAnalysis" :size="17" />效果评估资料</h4>
      <p class="model-detail-note">mAP 沿用当前 AP 评估口径，以百分比展示。这里只展示登记结果，不自动训练、测速或运行评测。</p>
      <dl class="model-detail-metrics model-primary-metrics"><div v-for="[key,label] in metrics" :key="key"><dt>{{ label }}</dt><dd :class="{'is-unknown':modelMetricNumber(model[key])==null}">{{ modelMetricNumber(model[key])==null ? '待核对' : modelMetric(model[key]) }}</dd></div></dl>
      <p class="model-detail-note">AP50、AP75 应分别核对原始评测报告，不能由 AP 推算。</p>
      <dl class="model-detail-metrics model-fact-metrics"><div><dt>整图未检出率（漏检率）</dt><dd>{{ emptyImages.value }}</dd></div><div><dt>实测速度 FPS</dt><dd>{{ modelFps(model.inferenceFps) }}</dd></div></dl>
      <p class="model-detail-note">{{ emptyImages.description }}。未检出表示没有任何类别目标通过本次阈值，Normal 检出也算检出；失败图片不计入分母，不等同有真实标注的漏检判定。</p>
      <dl class="model-detail-facts"><dt>训练图片数量</dt><dd>{{ modelTrainingImages(model.trainingImageCount) }}</dd><dt>训练完成日期 · UTC+8</dt><dd>{{ modelTime(model.trainingCompletedAt) }}</dd></dl>
      <details v-if="legacyMetrics.length" class="model-storage-details"><summary><AppIcon name="Document" :size="15" />其他历史指标<AppIcon class="model-storage-chevron" name="ArrowDown" :size="13" /></summary><p class="model-detail-note">保留已有登记，不作为当前模型的主评估指标。</p><dl class="model-detail-metrics"><div v-for="[key,label] in legacyMetrics" :key="key"><dt>{{ label }}</dt><dd>{{ modelMetricNumber(model[key])==null ? '待核对' : modelMetric(model[key]) }}</dd></div></dl></details>
      <dl class="model-detail-facts"><dt>评估数据集</dt><dd>{{ model.evaluationDataset || '未记录' }}</dd><dt>登记的平均耗时</dt><dd>{{ modelMilliseconds(model.avgInferenceMs) }}</dd><dt>资料状态</dt><dd><StatusBadge domain="modelEvaluation" :code="model.mlopsStatus" /></dd></dl>
      <div v-if="model.compatibilityNote" class="model-compatibility-note"><h5><AppIcon name="Connection" :size="15" />测试环境与兼容性说明</h5><div :key="model.compatibilityNote" class="model-detail-copy" :class="{'is-long':longText(model.compatibilityNote)}" :tabindex="longText(model.compatibilityNote) ? 0 : undefined" :role="longText(model.compatibilityNote) ? 'region' : undefined" :aria-label="longText(model.compatibilityNote) ? '兼容性完整说明，可使用方向键滚动' : undefined"><p>{{ model.compatibilityNote }}</p></div><p v-if="longText(model.compatibilityNote)" class="model-detail-reading-hint"><AppIcon name="Rank" :size="13" />完整兼容性说明可在上方区域内滚动阅读</p></div>
    </section>

    <section class="model-detail-group">
      <h4><AppIcon name="Operation" :size="17" />登记策略与使用</h4>
      <dl class="model-detail-facts"><dt>默认模型</dt><dd>{{ modelDefault(model.isDefault) }}</dd><dt>部署策略</dt><dd>{{ modelStrategy(model) }}</dd><dt>使用次数</dt><dd>{{ modelUsage(model.usageCount) }}</dd><dt>最近使用 · UTC+8</dt><dd>{{ modelTime(model.lastUsedAt) }}</dd></dl>
      <p class="model-detail-note">策略为登记资料，不是实际灰度比例、A/B 测试结果或服务器部署回执。</p>
    </section>

    <section class="model-detail-group">
      <h4><AppIcon name="DocumentCopy" :size="17" />版本说明</h4>
      <div :key="model.updateDescription" class="model-detail-copy" :class="{'is-long':longText(model.updateDescription)}" :tabindex="longText(model.updateDescription) ? 0 : undefined" :role="longText(model.updateDescription) ? 'region' : undefined" :aria-label="longText(model.updateDescription) ? '版本完整说明，可使用方向键滚动' : undefined"><p>{{ model.updateDescription || '未记录更新说明。' }}</p></div>
      <p v-if="longText(model.updateDescription)" class="model-detail-reading-hint"><AppIcon name="Rank" :size="13" />完整版本说明可在上方区域内滚动阅读</p>
      <dl class="model-detail-facts"><dt>上传人</dt><dd>{{ model.creator || '未记录' }}</dd><dt>上传时间 · UTC+8</dt><dd>{{ modelTime(model.uploadTime) }}</dd><dt>发布时间 · UTC+8</dt><dd>{{ modelTime(model.publishedAt) }}</dd></dl>
    </section>

    <details class="model-storage-details"><summary><AppIcon name="Document" :size="15" />存储登记与策略字段<AppIcon class="model-storage-chevron" name="ArrowDown" :size="13" /></summary><dl class="model-detail-facts"><dt>模型路径登记</dt><dd>{{ model.modelPath || '未记录' }}</dd><dt>策略代码</dt><dd>{{ model.deploymentStrategy || '未记录' }}</dd><dt>灰度比例</dt><dd>{{ model.canaryPercent==null ? '未记录' : model.canaryPercent+'%' }}</dd><dt>A/B 分组</dt><dd>{{ model.abGroup || '未记录' }}</dd><dt>回滚来源</dt><dd>{{ model.rollbackFromModelId ?? '未记录' }}</dd></dl><p class="model-detail-note">路径与策略字段仅供对照登记资料，不在此访问文件或重新核对实际部署。</p></details>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import {modelTime,modelMetric,modelMetricNumber,modelMilliseconds,modelUsage,modelDefault,modelStrategy,modelNextStep,modelPrimaryMetricFields,modelLegacyMetricFields,modelFps,modelTrainingImages,modelNoDetection} from '@/utils/detectionModelPresentation'

const props=defineProps({model:{type:Object,required:true}})
const metrics=modelPrimaryMetricFields
const emptyImages=computed(()=>modelNoDetection(props.model))
const legacyMetrics=computed(()=>modelLegacyMetricFields.filter(([key])=>props.model[key]!=null))
const longText=value=>typeof value==='string' && (value.length>480 || value.split(/\r?\n/).length>7)
</script>
<style scoped>
.detection-model-details{min-width:0}
.detection-model-heading{display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap}
.detection-model-symbol{display:grid;place-items:center;width:44px;height:44px;border-radius:11px;background:var(--app-primary-soft);color:var(--app-primary);flex:0 0 auto}
.detection-model-heading>.business-status{flex-shrink:0}
.detection-model-heading>div{flex:1;min-width:140px}
.detection-model-heading h3{margin:0;font-size:18px;color:var(--app-text);line-height:1.6;overflow-wrap:anywhere}
.detection-model-heading p{margin:5px 0 0;font-size:12px;line-height:1.8;color:var(--app-text-secondary);overflow-wrap:anywhere}
.model-next-step{padding:12px 14px;border-left:3px solid #afc9f7;border-radius:0 7px 7px 0;background:var(--app-primary-light);font-size:13px;line-height:1.9;color:var(--app-text-secondary);margin:20px 0}
.model-detail-group{padding:20px 0;border-bottom:1px solid var(--app-border);min-width:0}
.model-detail-group h4{display:flex;align-items:center;gap:8px;font-size:14px;color:var(--app-text);margin:0 0 14px;line-height:1.8}
.model-detail-group h4>.el-icon{color:var(--app-primary);flex:0 0 auto}
.model-detail-note{margin:12px 0 0;font-size:12px;line-height:1.9;color:var(--app-text-secondary);overflow-wrap:anywhere}
.model-detail-group>h4+.model-detail-note{margin-top:0}
.model-detail-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px 12px;margin:18px 0}
.model-detail-metrics>div{display:grid;gap:7px;min-width:0}
.model-detail-metrics dt{font-size:12px;color:var(--app-text-secondary);line-height:1.8;overflow-wrap:anywhere}
.model-detail-metrics dd{margin:0;font-size:19px;font-weight:650;color:var(--app-text);line-height:1.5;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.model-detail-metrics dd.is-unknown{font-size:13px;font-weight:400;color:var(--app-text-secondary);align-self:center}
.model-detail-metrics.model-primary-metrics{grid-template-columns:minmax(0,1fr);max-width:260px}
.model-fact-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
.model-primary-metrics dd{font-size:28px}
.model-detail-facts{display:grid;grid-template-columns:135px minmax(0,1fr);gap:10px 16px;font-size:13px;line-height:1.85;margin:16px 0 0}
.model-detail-facts dt{color:var(--app-text-secondary)}
.model-detail-facts dd{margin:0;min-width:0;overflow-wrap:anywhere;color:var(--app-text)}
.model-detail-copy{margin-top:12px;min-width:0;font-size:13px;line-height:1.9;color:var(--app-text)}
.model-detail-copy p{margin:0;font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}
.model-detail-copy.is-long{max-height:260px;max-height:min(260px,40dvh);overflow:auto;overscroll-behavior:contain;padding:2px 8px 2px 2px;border-bottom:1px solid var(--app-border);scrollbar-gutter:stable}
.model-detail-copy:focus-visible{outline:2px solid var(--app-primary);outline-offset:-2px;border-radius:3px}
.model-detail-reading-hint{display:flex;align-items:flex-start;gap:6px;margin:8px 0 0;font-size:12px;line-height:1.85;color:var(--app-text-secondary);overflow-wrap:anywhere}
.model-detail-reading-hint>.el-icon{flex:0 0 auto;margin-top:4px}
.model-compatibility-note{margin-top:18px;padding-top:14px;border-top:1px solid var(--app-border);min-width:0}
.model-compatibility-note h5{display:flex;align-items:center;gap:7px;margin:0;font-size:12px;font-weight:550;line-height:1.8;color:var(--app-text-secondary)}
.model-compatibility-note h5>.el-icon{color:var(--app-primary);flex:0 0 auto}
.model-storage-details{margin:18px 0;font-size:12px;line-height:1.8;color:var(--app-text-secondary)}
.model-storage-details summary{display:flex;align-items:center;flex-wrap:wrap;gap:6px;cursor:pointer;width:fit-content;color:var(--app-primary);transition:color 180ms ease}
.model-storage-details summary:hover{color:var(--app-primary-hover)}
.model-storage-details summary>.el-icon{flex:0 0 auto}
.model-storage-chevron{transition:transform 180ms ease}
.model-storage-details[open] summary .model-storage-chevron{transform:rotate(180deg)}
.model-storage-details summary:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px;border-radius:3px}
@media(max-width:600px){.model-detail-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.model-detail-facts{grid-template-columns:1fr;gap:4px}.model-detail-facts dd{margin-bottom:9px}}
@media(prefers-reduced-motion:reduce){.model-storage-details summary,.model-storage-chevron{transition:none}}
</style>
