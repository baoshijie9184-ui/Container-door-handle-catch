<template>
  <main class="task-board">
    <header class="board-heading"><div><h1>{{ supervisor ? '任务总表' : '我的任务' }}</h1><p>{{ supervisor ? 'OSS 文件夹、模型检测与人工校验' : '分派给我的检测与质检任务' }}</p></div>
      <el-button v-if="supervisor" type="primary" @click="openNew()"><AppIcon name="Plus"/>新建文件夹任务</el-button>
    </header>
    <section class="board-panel" aria-label="任务列表">
      <div v-if="!supervisor" class="inbox-scope"><el-checkbox v-model="inbox" @change="filter(phase)">只看待我处理</el-checkbox></div>
      <div class="board-toolbar"><div class="phases" aria-label="按任务阶段筛选">
        <button v-for="(label,key) in phases" :key="key" :aria-pressed="phase===key" @click="filter(key)">{{ label }}</button>
      </div><form @submit.prevent="search"><el-input v-model="query" placeholder="搜目录、任务或工号" aria-label="搜索任务" clearable @clear="search"/><el-button native-type="submit">查询</el-button></form></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <el-table :data="rows" v-loading="loading" row-key="taskId" empty-text="当前筛选下没有任务">
        <el-table-column label="任务 / OSS 目录" min-width="224"><template #default="{row}">
          <strong>{{ row.folder || row.taskId }}</strong><small :title="row.prefix">{{ row.prefix || '目录未记录' }}</small>
        </template></el-table-column>
        <el-table-column label="进度" min-width="140"><template #default="{row}">
          <b class="phase" :data-phase="row.phase">{{ phases[row.phase] }}</b>
          <small>模型已处理 {{ row.processedImages ?? 0 }} / {{ row.totalImages ?? '—' }} 张<span v-if="row.failedImages"> · {{ row.failedImages }} 张失败</span></small>
          <progress v-if="row.totalImages" :value="row.processedImages || 0" :max="row.totalImages" aria-label="模型图片处理进度"/>
        </template></el-table-column>
        <el-table-column label="检测员工" min-width="126"><template #default="{row}">{{ row.detectionOperator || row.detector || '—' }}<small v-if="row.detector">{{ row.detectionOperator ? '已执行检测' : '受派检测' }}</small></template></el-table-column>
        <el-table-column label="质检员工" min-width="126"><template #default="{row}">{{ row.qualityOperator || row.qualityAssignee || '—' }}<small v-if="row.qualityOperator || row.qualityAssignee">{{ row.reviewedAt ? '已提交复核' : '受派质检' }}</small></template></el-table-column>
        <el-table-column label="操作" min-width="215"><template #default="{row}">
          <div class="row-actions">
            <el-button v-if="Number(row.mine) && ['READY','FAILED'].includes(row.phase)" size="small" type="primary" @click="start(row)" :disabled="busy">{{ row.phase==='FAILED'?'重试模型检测':'启动模型检测' }}</el-button>
            <el-button v-if="supervisor && row.taskType==='OSS_FOLDER' && row.phase==='READY'" size="small" @click="openAssign(row)">改派检测</el-button>
            <router-link v-if="supervisor && canReview(row)" :to="quality(row,'assign')">分派质检</router-link>
            <router-link v-if="canReview(row) && (supervisor || row.qualityAssignee===user.username)" :to="quality(row,'review')">核对模型结果</router-link>
            <router-link :to="quality(row,'trace')">任务详情</router-link>
            <button v-if="supervisor && row.prefix" @click="openNew(row.prefix)">以此目录派单</button>
          </div>
        </template></el-table-column>
      </el-table>
      <footer><span>共 {{ total }} 项</span><el-pagination layout="prev, pager, next" :pager-count="5" :page-size="20" :total="total" :current-page="page" @current-change="turn"/></footer>
    </section>
    <el-dialog v-model="dialog" :title="target?'改派检测员工':'新建文件夹任务'" width="min(620px, 95vw)" destroy-on-close :close-on-click-modal="false">
      <el-form label-position="top" @submit.prevent>
        <el-form-item v-if="!target" label="OSS 原图文件夹">
          <div class="folder-field"><div class="path-bar"><el-input v-model="pathInput" aria-label="OSS 目录路径" placeholder="detection/…/" @keyup.enter="browse(pathInput)"/><el-button @click="browse(pathInput)">打开目录</el-button></div>
            <div class="folder-status"><button v-if="folder!=='detection/'" type="button" @click="browse(parentFolder)">上一级</button><span>{{ folder }}</span></div>
            <div v-loading="browsing" class="folder-children">
              <button v-for="child in children" :key="child" type="button" @click="browse(child)"><AppIcon name="FolderOpened" :size="15"/>{{ child.slice(folder.length,-1) }}</button>
              <button v-if="next" type="button" @click="browse(folder,next)">更多目录</button>
              <span v-if="!browsing && ready">本目录{{ folderImages ? '已找到 '+folderImages+' 张图片' : '当前尚未找到图片' }}</span>
            </div>
            <el-alert v-if="folderError" type="error" :title="folderError" :closable="false"/>
          </div>
        </el-form-item>
        <el-form-item label="检测员工工号"><QualityAssigneePicker v-model="recipient.username" v-model:user-id="recipient.userId" v-model:revision="recipient.revision" :disabled="busy"/></el-form-item>
        <el-alert v-if="saveError" type="error" :title="saveError" :closable="false"/>
      </el-form>
      <template #footer><el-button :disabled="busy" @click="dialog=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="!recipient.userId || (!target && (!ready || !folderImages || folder!==pathInput))" @click="save">确认派发</el-button></template>
    </el-dialog>
  </main>
</template>
<script setup>
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {useRoute} from 'vue-router'
import {ElMessage} from 'element-plus'
import {captureAccountRequest} from '@/api/request'
import QualityAssigneePicker from '@/components/QualityAssigneePicker.vue'
import {useUserStore} from '@/stores/user'
const user=useUserStore(),supervisor=computed(()=>user.role==='SUPERVISOR'),api=captureAccountRequest()
const inbox=ref(useRoute().query.inbox==='1')
const phases={'':'全部',READY:'未开始',DETECTING:'检测中',VERIFYING:'校验中',DONE:'完成',FAILED:'异常'}
const phase=ref(''),query=ref(''),keyword=ref(''),page=ref(1),total=ref(0),rows=ref([]),loading=ref(false),error=ref('')
const dialog=ref(false),target=ref(null),recipient=ref({}),busy=ref(false),saveError=ref(''),requestId=ref('')
const folder=ref('detection/'),pathInput=ref(''),children=ref([]),next=ref(null),folderImages=ref(0),folderError=ref(''),browsing=ref(false),ready=ref(false)
const parentFolder=computed(()=>folder.value.replace(/[^/]+\/$/,''))
let read=0,folderRead=0,timer
const url='/api/detection/board'
function data(response){if(response.data?.code!==200)throw Error(response.data?.message || '操作失败');return response.data.data}
const message=e=>e.response?.data?.message || e.message || '操作失败，请重试'
async function load(quiet=false){
  const generation=++read
  if(!quiet)loading.value=true
  try{const result=data(await api.get(url,{params:{page:page.value,size:20,inbox:inbox.value,keyword:keyword.value,phase:phase.value}}))
    if(generation===read){rows.value=result.items;total.value=result.total;error.value=''}
  }catch(e){if(generation===read)error.value=message(e)}finally{if(generation===read)loading.value=false}
}
function filter(key){phase.value=key;page.value=1;load()}
function search(){keyword.value=query.value.trim();page.value=1;load()}
function turn(value){page.value=value;load()}
const canReview=row=>row.phase==='VERIFYING' && ['PENDING_REVIEW','REVIEWING'].includes(row.flow) && row.reviewStatus==='PENDING'
const quality=(row,action)=>({path:'/quality/queue',query:{taskId:row.taskId,boardAction:action}})
function openNew(prefix='detection/'){
  target.value=null;recipient.value={};requestId.value=crypto.randomUUID();saveError.value='';dialog.value=true;browse(prefix)
}
function openAssign(row){target.value=row;recipient.value={};saveError.value='';dialog.value=true}
async function browse(value,marker){
  const generation=++folderRead
  const path=value.trim().replace(/\/?$/,'/')
  if(!marker){pathInput.value=path;folder.value=path;children.value=[];folderImages.value=0;next.value=null}
  browsing.value=true;ready.value=false;folderError.value=''
  try{const result=data(await api.get(url+'/folders',{params:{prefix:path,marker}}));if(generation!==folderRead)return
    children.value.push(...result.folders);next.value=result.next;folderImages.value+=result.imagesOnPage;ready.value=true
  }catch(e){if(generation===folderRead)folderError.value=message(e)}finally{if(generation===folderRead)browsing.value=false}
}
async function save(){
  if(busy.value)return
  busy.value=true;saveError.value=''
  try{
    if(target.value)data(await api.post(url+'/'+target.value.taskId+'/assign',{version:target.value.assignmentVersion,recipient:recipient.value}))
    else data(await api.post(url,{requestId:requestId.value,prefix:folder.value,recipient:recipient.value},{timeout:60000}))
    dialog.value=false;ElMessage.success('任务已派发');query.value='';keyword.value='';filter('')
  }catch(e){saveError.value=message(e)}finally{busy.value=false}
}
async function start(row){
  if(busy.value)return
  busy.value=true
  try{data(await api.post(url+'/'+row.taskId+'/start',null,{params:{version:row.assignmentVersion}}));ElMessage.success('模型检测已提交');await load()}
  catch(e){ElMessage.error(message(e));await load()}finally{busy.value=false}
}
onMounted(()=>{load();timer=setInterval(()=>{if(!document.hidden&&!dialog.value&&!busy.value&&!loading.value)load(true)},6000)})
watch(()=>user.accountContext,()=>{read++;folderRead++;rows.value=[];total.value=0;dialog.value=false})
onBeforeUnmount(()=>{clearInterval(timer);read++;folderRead++})
</script>
<style scoped>
.inbox-scope{padding:5px 15px 0}.task-board{display:grid;gap:18px;color:var(--app-text);min-width:0}.board-heading,.board-toolbar,.board-panel footer,.path-bar,.folder-status,.row-actions,.phases,.board-toolbar form{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.board-heading,.board-toolbar,.board-panel footer{justify-content:space-between}.board-heading h1{margin:0;font-size:28px}.board-heading p,.folder-status,.board-panel small,.board-panel footer>span{color:var(--app-text-secondary);font-size:12px}.board-heading p{margin:6px 0 0}.board-panel{min-width:0;border:1px solid var(--app-border);border-radius:12px;background:white;overflow:hidden}.board-toolbar,.board-panel footer{padding:15px}.board-toolbar form{flex-wrap:nowrap;max-width:100%}.board-panel small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.phases{gap:3px}.phases button,.row-actions button:not(.el-button),.folder-status button,.folder-children button{border:0;cursor:pointer;background:transparent;color:var(--app-primary);font:inherit}.phases button{padding:7px 10px;border-radius:6px;color:var(--app-text-secondary)}.phases button[aria-pressed=true]{background:var(--app-primary-soft);color:var(--app-primary);font-weight:650}.phase{font-size:13px}.phase[data-phase=DETECTING],.phase[data-phase=DONE]{color:#2156af}.phase[data-phase=VERIFYING]{color:#895005}.phase[data-phase=FAILED]{color:#a53d32}.board-panel progress{display:block;height:5px;width:100px;max-width:100%;margin-top:5px;accent-color:#2866da}.row-actions{gap:7px 12px}.row-actions a,.row-actions button:not(.el-button){color:var(--app-primary);text-decoration:none;font-size:13px;padding:0}.folder-field,.path-bar,.folder-children{width:100%}.path-bar{flex-wrap:nowrap}.folder-status{margin:8px 0;overflow-wrap:anywhere;line-height:1.4}.folder-children{display:grid;max-height:190px;overflow:auto;background:var(--app-surface-muted);padding:6px;border-radius:6px;min-height:36px}.folder-children button{display:flex;align-items:center;gap:7px;padding:5px;text-align:left}.folder-children span{font-size:12px}.board-panel footer{border-top:1px solid var(--app-border)}
</style>
