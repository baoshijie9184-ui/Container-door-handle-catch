<template>
  <div class="annotation-controls">
    <el-button v-if="allowEdit && view?.editable" size="small" :loading="opening" @click="openEditor"><AppIcon name="Edit" :size="15"/>调整标注</el-button>
    <template v-if="view?.edition">
      <span>人工标注 · {{ view.edition.employee }} · 第 {{ view.edition.revision }} 版</span>
      <a v-if="renderedUrl" :href="renderedUrl" :download="fileName+'-人工标注.jpg'">下载人工标注图</a>
    </template>
    <span v-if="error && !opened" role="alert">{{ error }} <button type="button" @click="load">重试</button></span>
    <el-dialog v-model="opened" append-to-body destroy-on-close title="调整标注" width="min(1080px, 96vw)"
      class="annotation-edit-dialog" :before-close="askClose" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
      <div v-if="view?.model" class="annotation-editor">
        <div class="annotation-stage">
          <svg ref="svg" :viewBox="'0 0 '+width+' '+height" role="group" aria-label="原图标注编辑区"
            @pointermove="dragMove" @pointerup="endDrag" @pointercancel="cancelDrag" @lostpointercapture="endDrag">
            <image :href="originalUrl" :width="width" :height="height"/>
            <g v-for="(t,i) in draft" :key="i">
              <rect :x="t.box[0]" :y="t.box[1]" :width="t.box[2]-t.box[0]" :height="t.box[3]-t.box[1]"
                :stroke="i===selected?'#1665ee':'#f3a334'" class="edit-box" :class="{active:i===selected}" @pointerdown="startDrag($event,i,'move')"/>
            </g>
            <g v-if="current">
              <text :x="Math.min(current.box[0]+2,Math.max(1,width-fontSize*5))" :y="Math.max(fontSize,current.box[1]-5)"
                :font-size="fontSize" class="edit-label">{{ annotationClasses[current.label][0] }}</text>
              <rect :x="current.box[0]" :y="current.box[1]" :width="current.box[2]-current.box[0]" :height="current.box[3]-current.box[1]"
                class="selected-outline" @pointerdown="startDrag($event,selected,'move')"/>
              <circle v-for="c in corners" :key="c.mode" :cx="c.x" :cy="c.y" :r="handleSize" class="handle"
                :style="{cursor:c.mode+'-resize'}" @pointerdown.stop="startDrag($event,selected,c.mode)"/>
            </g>
          </svg>
        </div>
        <div class="annotation-fields">
          <label>检测目标<select v-model.number="selected" :disabled="!draft.length || saving">
            <option v-for="(t,i) in draft" :key="i" :value="i">目标 {{ i+1 }} · {{ annotationClasses[t.label][0] }}</option>
          </select></label>
          <template v-if="current">
            <label>标注类别<select v-model="current.label" :disabled="saving">
              <option v-for="([label],code) in annotationClasses" :key="code" :value="code">{{label}}</option>
            </select></label>
            <div class="coordinate-fields">
              <label v-for="(label,i) in axisLabels" :key="label">{{ label }}<input type="number" step="any" :disabled="saving"
                :value="Number(current.box[i].toFixed(2))" @change="setCoordinate(i,$event)"/></label>
            </div>
            <p>拖动框内移动，拖动角点缩放。重叠框可从「检测目标」切换。</p>
          </template>
          <p v-else>这张图没有检测框。</p>
        </div>
      </div>
      <p v-if="error" class="annotation-error" role="alert">{{error}}</p>
      <template #footer>
        <span class="annotation-filename">{{fileName}}</span>
        <el-button :disabled="saving" @click="askClose(()=>opened=false)">取消</el-button>
        <el-button type="primary" :disabled="!dirty || !current || blocked" :loading="saving" @click="save">保存标注</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { captureAccountRequest } from '@/api/request'
import AppIcon from './AppIcon.vue'
import { annotationClasses, moveBox, renderReviewedImage } from '../utils/annotationGeometry'

const props=defineProps({ taskId:String, sourceKey:String, originalUrl:String, fileName:String, allowEdit:Boolean })
const emit=defineEmits(['rendition'])
const api=captureAccountRequest(), endpoint='/api/detection/tasks/'+encodeURIComponent(props.taskId)+'/annotations'
const view=ref(null), opened=ref(false), opening=ref(false), saving=ref(false), blocked=ref(false), error=ref(''), renderedUrl=ref('')
const draft=ref([]), originalDraft=ref(''), selected=ref(0), svg=ref(null)
const current=computed(()=>draft.value[selected.value]), dirty=computed(()=>JSON.stringify(draft.value)!==originalDraft.value)
const width=computed(()=>view.value?.model?.width || 1), height=computed(()=>view.value?.model?.height || 1)
const fontSize=computed(()=>Math.max(12,Math.min(width.value,height.value)*.04))
const handleSize=computed(()=>Math.max(3,Math.min(width.value,height.value)*.012))
const axisLabels=['左边界','上边界','右边界','下边界']
const corners=computed(()=>{
  if(!current.value)return []
  const [l,t,r,b]=current.value.box
  return [{mode:'nw',x:l,y:t},{mode:'ne',x:r,y:t},{mode:'sw',x:l,y:b},{mode:'se',x:r,y:b}]
})
const controller=new AbortController()
let drag=null
function unpack(r){
  if(r.data?.code!==200)throw Object.assign(Error(r.data?.message || '请求失败'),{code:r.data?.code})
  return r.data.data
}
async function applyView(data){
  if(controller.signal.aborted)return
  view.value=data
  if(!data.edition)return
  const blob=await renderReviewedImage(props.originalUrl,data.edition)
  if(controller.signal.aborted)return
  const previous=renderedUrl.value
  renderedUrl.value=URL.createObjectURL(blob)
  emit('rendition',{url:renderedUrl.value,edition:data.edition})
  if(previous)URL.revokeObjectURL(previous)
}
function read(withModel){return api.get(endpoint,{params:{sourceKey:props.sourceKey,withModel},signal:controller.signal}).then(unpack)}
async function load(){
  error.value=''
  try{await applyView(await read(false))}
  catch(e){if(!controller.signal.aborted)error.value=e.response?.data?.message || e.message || '标注读取失败'}
}
async function openEditor(){
  opening.value=true;error.value='';blocked.value=false
  try{
    const data=await read(true)
    if(controller.signal.aborted)return
    if(!data.editable)throw Error('当前任务已结束复核或已重新分派')
    // The clean image and model use the same EXIF-oriented pixel space.
    const img=new Image()
    img.src=props.originalUrl;await img.decode()
    if(controller.signal.aborted)return
    if(img.naturalWidth!==data.model.width || img.naturalHeight!==data.model.height)throw Error('原图尺寸与模型标注不一致')
    view.value=data;draft.value=JSON.parse(JSON.stringify(data.edition?.targets || data.model.targets))
    selected.value=0;originalDraft.value=JSON.stringify(draft.value);opened.value=true
  }catch(e){if(!controller.signal.aborted)error.value=e.response?.data?.message || e.message}
  finally{opening.value=false}
}
function point(event){
  const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(svg.value.getScreenCTM().inverse())
  return {x:p.x,y:p.y}
}
function startDrag(event,index,mode){
  if(saving.value || event.button!==0 || drag)return
  event.preventDefault();selected.value=index
  drag={...point(event),index,mode,box:[...draft.value[index].box],id:event.pointerId}
  svg.value.setPointerCapture(event.pointerId)
}
function dragMove(event){
  if(!drag || drag.id!==event.pointerId)return
  const p=point(event)
  draft.value[drag.index].box=moveBox(drag.box,drag.mode,p.x-drag.x,p.y-drag.y,width.value,height.value)
}
function endDrag(event){if(drag?.id===event.pointerId)drag=null}
function cancelDrag(event){if(drag?.id===event.pointerId){draft.value[drag.index].box=drag.box;drag=null}}
function setCoordinate(i,event){
  const box=current.value.box,value=event.target.valueAsNumber,delta=value-box[i]
  if(Number.isFinite(value))current.value.box=moveBox(box,['w','n','e','s'][i],i%2?0:delta,i%2?delta:0,width.value,height.value)
  event.target.value=Number(current.value.box[i].toFixed(2))
}
async function askClose(done){
  if(saving.value)return
  if(dirty.value){try{await ElMessageBox.confirm('放弃本次未保存的标注调整？','关闭编辑',{confirmButtonText:'放弃调整',cancelButtonText:'继续编辑'})}catch{return}}
  drag=null;done()
}
async function save(){
  saving.value=true;error.value=''
  try{
    const data=unpack(await api.post(endpoint,{sourceKey:props.sourceKey,basis:view.value.model.basis,revision:view.value.edition?.revision || 0,targets:draft.value},{signal:controller.signal}))
    if(controller.signal.aborted)return
    originalDraft.value=JSON.stringify(draft.value);opened.value=false
    ElMessage.success('人工标注已保存')
    await applyView(data)
  }catch(e){
    if(!controller.signal.aborted){
      const code=e.response?.data?.code || e.code
      blocked.value=[403,409].includes(Number(code))
      error.value=e.response?.data?.message || e.message || '标注保存失败'
    }
  }finally{saving.value=false}
}
onMounted(load)
onBeforeUnmount(()=>{controller.abort();if(renderedUrl.value)URL.revokeObjectURL(renderedUrl.value)})
</script>
<style>
@font-face{font-family:ReviewSong;src:url('../assets/annotation/annotation-song.otf') format('opentype');font-display:swap}
.annotation-controls{display:flex;align-items:center;flex-wrap:wrap;gap:8px 14px;margin-bottom:8px;color:var(--app-text-secondary);font-size:12px}
.annotation-controls:empty{display:none}.annotation-controls a{color:var(--app-primary)}
.annotation-edit-dialog.el-dialog{margin-top:4vh;max-height:92vh;overflow:auto}.annotation-editor{display:grid;grid-template-columns:minmax(0,1fr) 190px;gap:18px}
.annotation-stage{display:grid;place-items:center;background:#edf1f6;border-radius:8px;overflow:hidden}
.annotation-stage svg{width:100%;max-height:65vh;touch-action:none;user-select:none}
.annotation-stage .edit-box{stroke-width:2;vector-effect:non-scaling-stroke;fill:transparent;cursor:move}
.annotation-stage .active{stroke-width:3}.annotation-stage .handle{fill:#fff;stroke:#165cd4;stroke-width:2;vector-effect:non-scaling-stroke}
.selected-outline{fill:transparent;stroke:transparent;stroke-width:3;pointer-events:all;cursor:move}
.annotation-stage .edit-label{fill:white;stroke:#143967;stroke-width:3px;paint-order:stroke;font-family:ReviewSong,serif;pointer-events:none}
.annotation-fields{display:grid;align-content:start;gap:12px}.annotation-fields label{display:grid;gap:5px;font-size:13px;color:var(--app-text)}
.annotation-fields select,.annotation-fields input{width:100%;padding:6px;border:1px solid var(--app-border);background:white;border-radius:5px;color:var(--app-text)}
.coordinate-fields{display:grid;grid-template-columns:1fr 1fr;gap:8px}.annotation-fields p,.annotation-filename{font-size:12px;color:var(--app-text-secondary)}
.annotation-filename{margin-right:auto;overflow-wrap:anywhere}.annotation-edit-dialog .el-dialog__footer{display:flex;align-items:center;gap:6px}.annotation-error{color:#a02920}
@media(max-width:700px){.annotation-editor{grid-template-columns:1fr}.annotation-fields{grid-template-columns:1fr 1fr}.coordinate-fields,.annotation-fields p{grid-column:1/-1}}
</style>
