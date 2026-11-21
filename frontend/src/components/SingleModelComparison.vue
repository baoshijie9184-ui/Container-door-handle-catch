<template>
  <section class="compare" aria-label="单图双模型对比" :aria-busy="busy">
    <div class="compare-toolbar">
      <input ref="picker" type="file" accept="image/jpeg,image/png" hidden @change="choose($event.target.files?.[0])" />
      <el-button :disabled="busy" @click="picker.click()"><AppIcon name="Upload" :size="15" />{{ file ? '更换图片' : '选择图片' }}</el-button>
      <label class="threshold">置信度阈值 <el-input-number v-model="threshold" aria-label="对比置信度阈值" :min="0" :max="1" :step="0.05" :precision="2" :disabled="busy" @change="clearResults" /></label>
      <el-button type="primary" :loading="busy" :disabled="!canStart" @click="start"><AppIcon name="VideoPlay" :size="16" />开始对比</el-button>
    </div>
    <p v-if="fileError || catalogError" class="compare-error" role="alert">{{ fileError || catalogError }}
      <el-button v-if="catalogError" link type="primary" :loading="reading" @click="readModels">重新读取模型</el-button>
    </p>

    <div class="comparison-grid">
      <figure class="comparison-frame" @dragover.prevent @drop.prevent="choose($event.dataTransfer.files[0])">
        <figcaption><h3><AppIcon name="Picture" :size="17" />原图</h3><span class="file-name" :title="file?.name">{{ file?.name || 'JPG / PNG' }}</span></figcaption>
        <button v-if="sourceUrl" type="button" class="image-area" aria-label="放大原图" @click="zoom={title:'原图',url:sourceUrl}"><img :src="sourceUrl" alt="本次对比原图" /></button>
        <button v-else type="button" class="image-area upload-area" @click="picker.click()"><AppIcon name="Upload" :size="24" />选择或拖入图片</button>
      </figure>

      <figure v-for="(lane,index) in lanes" :key="lane.label" class="comparison-frame">
        <figcaption>
          <h3><AppIcon name="View" :size="17" />模型 {{ lane.label }}<span v-if="lane.stage !== 'IDLE'" class="run-state" role="status">{{ stageLabel(lane.stage) }}</span></h3>
          <el-select :model-value="lane.modelId" :aria-label="'选择模型 '+lane.label" placeholder="选择检测模型" :loading="reading" :disabled="busy || !models.length" @change="selectModel(index,$event)">
            <el-option v-for="model in models" :key="model.modelId" :value="model.modelId" :label="model.modelName+' · '+model.version" />
          </el-select>
        </figcaption>
        <button v-if="lane.result && !lane.imageError" type="button" class="image-area" :aria-label="'放大模型 '+lane.label+' 标注图'" @click="zoom={title:'模型 '+lane.label,url:lane.result.annotatedImagePath}">
          <img :key="lane.attempt" :src="lane.result.annotatedImagePath" :alt="'模型 '+lane.label+' 标注图'" @error="lane.imageError=true" />
        </button>
        <div v-else class="image-area empty-image" aria-live="polite">
          <AppIcon :name="lane.imageError || ['UNCONFIRMED','FAILED'].includes(lane.stage) ? 'Warning' : 'Picture'" :size="24" />
          <span>{{ lane.imageError ? '标注图读取失败' : lane.message || '等待检测' }}</span>
          <el-button v-if="lane.imageError" link type="primary" @click="lane.attempt++;lane.imageError=false">重新读取图片</el-button>
        </div>
        <div v-if="lane.result || lane.taskId || lane.stage==='FAILED'" class="result-line">
          <strong v-if="lane.result">{{ lane.result.targetCount }} 个目标<span v-if="lane.result.confidence != null"> · {{ category(lane.result.category) }} {{ Math.round(lane.result.confidence*100) }}%</span></strong>
          <button v-if="lane.taskId" type="button" @click="$emit('trace',lane.taskId)">查看任务记录</button>
          <button v-if="lane.stage==='FAILED'" type="button" :disabled="busy" @click="runLane(lane)">重试模型 {{ lane.label }}</button>
        </div>
      </figure>
    </div>
    <el-dialog :model-value="!!zoom" :title="zoom?.title" width="min(92vw, 1080px)" append-to-body destroy-on-close @close="zoom=null">
      <img v-if="zoom" class="zoom-image" :src="zoom.url" :alt="zoom.title" />
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { captureAccountRequest } from '../api/request'
import { detectSingleImageViaKafka } from '../services/singleImageKafkaDetection'
import { CATEGORY_ALIASES, CATEGORY_LABELS } from '../stores/detectionTask'
import { statusPresentation } from '../utils/statusPresentation'

const emit = defineEmits(['trace','busy'])
const lanes = reactive(['A','B'].map(label=>({label,modelId:null,...initialResult()})))
function initialResult() { return {stage:'IDLE',pending:false,message:'',taskId:'',result:null,imageError:false,attempt:0} }
const models=ref([]), reading=ref(false), catalogError=ref(''), fileError=ref('')
const picker=ref(null), file=shallowRef(null), sourceUrl=ref(''), zoom=ref(null), threshold=ref(0.5)
let active=true
const busy=computed(()=>lanes.some(lane=>lane.pending))
watch(busy,value=>emit('busy',value),{flush:'sync'})
const canStart=computed(()=>file.value && !busy.value && Number.isFinite(threshold.value) && lanes.every(l=>l.modelId && l.stage!=='UNCONFIRMED') && lanes[0].modelId!==lanes[1].modelId)
const category=label=>CATEGORY_LABELS[CATEGORY_ALIASES[label] || label] || label
const stageLabel=stage=>statusPresentation('singleDetection',stage).label

async function readModels() {
  if (reading.value) return
  reading.value=true
  catalogError.value=''
  try {
    const response=await captureAccountRequest().get('/api/models/single-test-models')
    if (!active) return
    if (response.data?.code!==200 || !Array.isArray(response.data.data)) throw new Error()
    models.value=response.data.data
    lanes.forEach((lane,index)=>{lane.modelId=models.value[index]?.modelId || null})
    if (models.value.length<2) catalogError.value='当前可用于对比的模型不足两个。'
  } catch { if(active) catalogError.value='检测模型目录读取失败。' }
  finally { if(active) reading.value=false }
}
function clearResults() { if (!busy.value) lanes.forEach(lane=>Object.assign(lane,initialResult())) }
function selectModel(index,id) {
  if (busy.value || lanes[index].modelId===id) return
  const other=lanes[1-index]
  if (other.modelId===id) other.modelId=lanes[index].modelId
  lanes[index].modelId=id
  clearResults()
}
function choose(next) {
  if (picker.value) picker.value.value=''
  if (busy.value || !next) return
  if (!['image/png','image/jpeg'].includes(next.type) || !next.size || next.size>10*1024*1024) {
    fileError.value='请选择 10 MB 以内的 JPG 或 PNG 图片。'
    return
  }
  fileError.value=''
  zoom.value=null
  if (sourceUrl.value) URL.revokeObjectURL(sourceUrl.value)
  sourceUrl.value=URL.createObjectURL(next)
  file.value=next
  clearResults()
}
async function runLane(lane) {
  if (!file.value || !lane.modelId || lane.pending) return
  Object.assign(lane,initialResult(),{pending:true,stage:'CREATING',message:'正在登记检测任务'})
  try {
    const result=await detectSingleImageViaKafka({file:file.value,modelId:lane.modelId,threshold:threshold.value,
      onStatus:({taskId,stage,message})=>{
        if (!active) return
        if (taskId) lane.taskId=taskId
        if (stage) lane.stage=stage
        if (message) lane.message=message
      }})
    if (!active) return
    lane.taskId=result.taskId
    lane.result=result
    lane.stage=result.status
  } catch(error) {
    if (!active) return
    lane.stage=error.taskFailed ? 'FAILED' : 'UNCONFIRMED'
    lane.message=error.message || '请核对检测记录'
  } finally { if (active) lane.pending=false }
}
function start() { if (canStart.value) return Promise.all(lanes.map(runLane)) }
onMounted(readModels)
onBeforeUnmount(()=>{active=false;emit('busy',false);if(sourceUrl.value) URL.revokeObjectURL(sourceUrl.value)})
</script>

<style scoped>
.compare { display:grid;gap:16px;min-width:0 }
.compare-toolbar,.threshold,.result-line,.comparison-frame h3 { display:flex;align-items:center;gap:10px }
.compare-toolbar,.result-line { flex-wrap:wrap }.compare-toolbar .el-button { margin:0;gap:6px }.threshold { font-size:13px;color:var(--app-text-secondary) }.threshold .el-input-number { width:116px }
.compare-toolbar .el-button--primary { margin-left:auto }.compare-error { margin:0;color:var(--el-color-danger);font-size:13px }
.comparison-grid { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px }
.comparison-frame { min-width:0;align-self:start;margin:0;border:1px solid var(--app-border);border-radius:9px;overflow:hidden;background:white }
.comparison-frame figcaption { padding:12px;display:grid;grid-template-rows:22px 32px;gap:7px }
.comparison-frame h3 { margin:0;font-size:14px;line-height:22px;color:var(--app-text) }.comparison-frame h3 :deep(svg) { color:var(--app-primary) }
.file-name,.run-state,.empty-image,.upload-area { color:var(--app-text-secondary);font-size:12px }.file-name { line-height:32px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap }
.run-state { margin-left:auto;font-weight:500 }.image-area { width:100%;aspect-ratio:4/3;display:flex;flex-direction:column;gap:9px;align-items:center;justify-content:center;border:0;border-top:1px solid var(--app-border);background:var(--app-bg-alt,#f4f7fb);padding:0;text-align:center }
button.image-area { cursor:zoom-in }button.upload-area { cursor:pointer;color:var(--app-primary) }.image-area img { height:100%;width:100%;min-height:0;object-fit:contain }.empty-image { padding:10px;overflow:auto;overflow-wrap:anywhere }
.result-line { padding:10px 12px;font-size:12px;line-height:1.6 }.result-line button { background:none;border:0;color:var(--app-primary);cursor:pointer;padding:2px }
.zoom-image { width:100%;max-height:72vh;object-fit:contain }.image-area:focus-visible { outline:2px solid var(--app-primary);outline-offset:-3px }
@media(max-width:800px){.comparison-grid {grid-template-columns:1fr}.image-area {max-height:360px}.compare-toolbar .el-button--primary {margin-left:0}}
</style>
