<template>
  <main class="task-board">
    <header class="board-heading">
      <div class="board-title">
        <span class="board-mark" aria-hidden="true"><AppIcon :name="boardIcon" :size="22" /></span>
        <h1>{{ uploadsOnly || taskList ? route.meta.title : inboxTitle || boardTitle }}</h1>
      </div>
      <nav class="board-links" aria-label="相关操作">
        <router-link v-if="supervisor && (uploadsOnly || taskList)" to="/inspection/tasks"><AppIcon name="Tickets" :size="16"/>任务总表</router-link>
        <router-link v-if="!supervisor && uploadsOnly" :to="employeeScopeLink(true)"><AppIcon name="Tickets" :size="16"/>我的待办</router-link>
        <el-button v-if="supervisor && !uploadsOnly && !verificationList" type="primary" @click="openNew()"><AppIcon name="Plus"/>新建文件夹任务</el-button>
      </nav>
    </header>
    <InspectionFlowNav class="board-flow" />
    <WorkUnitApplications v-if="showApplications" :key="user.accountContext" :keyword="applicationKeyword" />
    <div v-if="applicationId" class="application-dispatch" aria-live="polite">
      <div v-if="application">
        <strong>{{ application.status==='WAITING' ? '为检测申请选择原图批次' : '为已批准的申请补选原图批次' }}</strong>
        <p>{{ application.applicantUserId }} · {{ application.workUnitId }} · 最多 {{ application.imageCount }} 张</p>
      </div>
      <p v-else>{{ applicationError || '正在读取检测申请…' }}</p>
      <router-link to="/home">返回工作台</router-link>
    </div>
    <section class="board-panel" :aria-label="uploadsOnly ? '上传记录' : '任务列表'">
      <div v-if="uploadsOnly" class="upload-navigation">
        <nav class="upload-scopes" aria-label="上传记录范围">
          <router-link v-if="supervisor" to="/inspection/uploads/dispatch">待派检测</router-link>
          <router-link to="/inspection/uploads/mine">我的上传</router-link>
          <router-link to="/inspection/uploads/all">全部上传</router-link>
        </nav>
        <form v-if="uploadScope==='mine'" class="colleague-search" role="search" aria-label="查他人上传" @submit.prevent="searchColleague">
          <el-input v-model="uploaderInput" maxlength="50" placeholder="输入员工工号" aria-label="上传人工号" clearable/>
          <el-button native-type="submit" :disabled="!uploaderInput.trim()">查他人上传</el-button>
        </form>
      </div>
      <div v-if="directory" class="directory-filter"><span>图片文件夹 <strong>{{ imageFolderLabel(directory) }}</strong></span><el-button link @click="changeFilters({ directory: undefined, page: undefined })">清除目录筛选</el-button></div>
      <div v-if="!supervisor && !uploadsOnly" class="upload-navigation">
        <nav class="upload-scopes" aria-label="我的任务范围">
          <router-link v-for="scope in employeeScopes" :key="scope.value" :to="employeeScopeLink(scope.value)" custom v-slot="{ href, navigate }">
            <a :href="href" :aria-current="inbox === scope.value ? 'page' : 'false'" @click="navigate">{{ scope.label }}</a>
          </router-link>
        </nav>
      </div>
      <div class="board-toolbar">
        <div v-if="(!uploadsOnly || supervisor || uploadScope==='mine') && !awaitingDispatch && inboxKind!=='verification'" class="phases" role="group" aria-label="按任务阶段筛选">
          <button v-for="(label,key) in listPhases" :key="key" type="button" :aria-pressed="phase===key" @click="filter(key)">{{ label }}</button>
        </div>
        <form class="task-search" role="search" aria-label="筛选任务" @submit.prevent="search">
          <el-input v-if="uploadsOnly && uploadScope==='team'" v-model="uploaderInput" maxlength="50" placeholder="上传人工号" aria-label="上传人工号" clearable @clear="search"/>
          <el-input v-model="query" maxlength="255" :placeholder="uploadsOnly ? '搜文件夹或任务号' : '搜目录、任务或工号'" aria-label="搜索任务" clearable @clear="search">
            <template #prefix><AppIcon name="Search" :size="15" /></template>
          </el-input>
          <el-button native-type="submit" type="primary" plain>查询</el-button>
        </form>
      </div>
      <div v-if="error" class="board-error" role="alert">
        <AppIcon name="Warning" :size="17" /><span>{{ error }}</span>
        <el-button link type="primary" :disabled="loading" @click="load()">重新读取</el-button>
      </div>
      <div class="board-results" v-loading="loading" :aria-busy="loading">
      <div v-if="!rows.length" class="board-empty">
        <template v-if="!loading && !error">
          <AppIcon name="FolderOpened" :size="26" aria-hidden="true" />
          <p>{{ emptyMessage }}</p>
          <router-link v-if="awaitingDispatch || (uploadsOnly && uploadScope==='mine' && !keyword && !phase)" to="/inspection/uploads/all">查看全部上传</router-link>
          <router-link v-else-if="inbox && !keyword && !phase" :to="employeeScopeLink(false)">查看全部任务</router-link>
          <router-link v-else-if="taskList==='detection' && keyword" :to="{path:'/inspection/tasks/verification',query:{keyword}}">在校验列表查找</router-link>
        </template>
      </div>
      <el-table v-else class="board-table" :data="rows" row-key="taskId">
        <el-table-column label="图片文件夹" min-width="195"><template #default="{row}">
          <strong class="folder-name" :title="recordFolderLabel(row)">{{ recordFolderLabel(row) }}</strong>
          <div class="folder-metadata">
            <span v-if="uploadsOnly">{{ row.totalImages ?? '—' }} 张图片</span>
            <FolderMetadataLink :task-id="row.taskId" />
          </div>
        </template></el-table-column>
        <el-table-column v-if="uploadsOnly" label="上传人" min-width="150"><template #default="{row}">
          <div><span class="person-label">工号：</span>{{ row.creator || '未关联' }}</div>
          <div><span class="person-label">姓名：</span>{{ row.creatorName || '—' }}</div>
        </template></el-table-column>
        <el-table-column v-if="uploadsOnly" label="登记时间" min-width="155"><template #default="{row}">
          {{ row.registeredAt || '—' }}
        </template></el-table-column>
        <el-table-column v-if="uploadsOnly && !awaitingDispatch" label="批次处理状态" min-width="145"><template #default="{row}">
          <template v-if="Number(row.uploadPending)">上传待确认</template>
          <template v-else-if="!Number(row.canReadTask)">已登记</template>
          <template v-else>
            <strong>{{ modelStep(row) }}</strong>
            <small>{{ humanStep(row) }}</small>
            <small v-if="row.totalImages != null">已处理 {{ row.processedImages ?? '—' }} / {{ row.totalImages }} 张<span v-if="row.failedImages"> · {{ row.failedImages }} 张失败</span></small>
            <progress v-if="row.totalImages && ['QUEUED','DETECTING','RUNNING'].includes(row.modelStatus)" :value="row.processedImages" :max="row.totalImages" aria-label="模型图片处理进度"/>
          </template>
        </template></el-table-column>
        <el-table-column v-if="!uploadsOnly" label="模型检测" min-width="148"><template #default="{row}">
          <TaskBoardStage :row="row" />
        </template></el-table-column>
        <el-table-column v-if="!uploadsOnly && taskList!=='detection'" label="人工校验" min-width="145"><template #default="{row}">
          <TaskBoardStage :row="row" verification />
        </template></el-table-column>
        <el-table-column label="操作" min-width="245"><template #default="{row}">
          <TaskBoardActions v-bind="rowActions(row)" @start="start" @assign="openAssign" @dispatch="openNew" @recheck="startRecheck" />
        </template></el-table-column>
      </el-table>
      <ul v-if="rows.length" class="board-cards" aria-label="任务与批次">
        <li v-for="row in rows" :key="row.taskId" class="board-card">
          <header class="board-card-heading">
            <div>
              <h2>{{ recordFolderLabel(row) }}</h2>
              <small v-if="row.totalImages != null">{{ row.totalImages }} 张图片</small>
            </div>
            <FolderMetadataLink :task-id="row.taskId" />
          </header>
          <dl class="card-facts">
            <template v-if="uploadsOnly">
              <div><dt>上传人</dt><dd>{{ [row.creator, row.creatorName].filter(Boolean).join(' · ') || '未关联' }}</dd></div>
              <div><dt>登记时间</dt><dd>{{ row.registeredAt || '—' }}</dd></div>
              <template v-if="!awaitingDispatch">
                <div v-if="Number(row.uploadPending) || !Number(row.canReadTask)"><dt>批次状态</dt><dd>{{ Number(row.uploadPending) ? '上传待确认' : '已登记' }}</dd></div>
                <template v-else>
                  <div><dt>模型检测</dt><dd><TaskBoardStage :row="row" /></dd></div>
                  <div><dt>人工校验</dt><dd><TaskBoardStage :row="row" verification /></dd></div>
                </template>
              </template>
            </template>
            <template v-else>
              <div><dt>模型检测</dt><dd><TaskBoardStage :row="row" /></dd></div>
              <div v-if="taskList!=='detection'"><dt>人工校验</dt><dd><TaskBoardStage :row="row" verification /></dd></div>
            </template>
          </dl>
          <TaskBoardActions v-bind="rowActions(row)" class="board-card-actions" @start="start" @assign="openAssign" @dispatch="openNew" @recheck="startRecheck" />
        </li>
      </ul>
      </div>
      <footer><span>{{ loading ? '正在读取…' : '共 '+total+' 项' }}</span><el-pagination v-if="total>20" layout="prev, pager, next" :pager-count="5" :page-size="20" :total="total" :current-page="page" @current-change="turn"/></footer>
    </section>
    <TaskDialogs v-if="activeAction" :key="activeAction.action + ':' + activeAction.taskId" :board-request="activeAction" @dismiss="closeAction" />
    <el-dialog v-model="dialog" :title="applicationId ? '确认申请派单' : target ? '改派检测员工' : sourceUpload ? '派发检测任务' : '新建文件夹任务'" width="min(620px, 95vw)" destroy-on-close :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy">
      <el-form label-position="top" @submit.prevent>
        <el-form-item v-if="sourceUpload" label="原图文件夹">
          <strong>{{ recordFolderLabel(sourceUpload) }}</strong><FolderMetadataLink :task-id="sourceUpload.taskId" />
        </el-form-item>
        <el-form-item v-else-if="!target" label="原图文件夹">
          <div class="folder-field">
            <div class="folder-status">
              <button v-if="folder && folder!=='detection/'" type="button" @click="browse(parentFolder)">上一级</button>
              <strong>{{ imageFolderLabel(folder) || '图片上传' }}</strong>
              <button type="button" :aria-expanded="editingPath" @click="togglePath">{{ editingPath ? '收起路径' : '输入路径' }}</button>
            </div>
            <div v-if="editingPath" class="path-bar"><el-input v-model="pathInput" aria-label="OSS 目录路径" placeholder="detection/…/" @keyup.enter="browse(pathInput)"/><el-button @click="browse(pathInput)">打开目录</el-button></div>
            <div v-loading="browsing" class="folder-children">
              <button v-for="child in folderChoices" :key="child.path" type="button" @click="browse(child.path)"><AppIcon name="FolderOpened" :size="15"/>{{ child.label }}</button>
              <button v-if="next" type="button" @click="browse(folder,next)">更多目录</button>
              <span v-if="!browsing && ready">本目录{{ folderImages ? '已找到 '+folderImages+' 张图片' : '当前尚未找到图片' }}</span>
            </div>
            <details v-if="ready && !browsing" class="picked-folder-metadata" :key="folder"><summary>详细数据</summary><dl><dt>OSS 目录</dt><dd><code>{{ folder }}</code></dd></dl></details>
            <el-alert v-if="folderError" type="error" :title="folderError" :closable="false"/>
          </div>
        </el-form-item>
        <el-form-item label="检测员工工号">
          <strong v-if="applicationId">{{ application?.applicantUserId }}</strong>
          <QualityAssigneePicker v-else v-model="recipient.username" v-model:user-id="recipient.userId" v-model:revision="recipient.revision" account-label="检测员工工号" :disabled="busy"/>
        </el-form-item>
        <el-alert v-if="saveError" type="error" :title="saveError" :closable="false"/>
      </el-form>
      <template #footer><el-button :disabled="busy" @click="dialog=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="!canSubmit" @click="save">确认派发</el-button></template>
    </el-dialog>
  </main>
</template>
<script setup>
import {computed,defineAsyncComponent,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {ElMessage,ElMessageBox} from 'element-plus'
import {captureAccountRequest} from '@/api/request'
import {imageFolderLabel,recordFolderLabel} from '@/utils/imageFolderLabel'
import InspectionFlowNav from '@/components/InspectionFlowNav.vue'
import FolderMetadataLink from '@/components/FolderMetadataLink.vue'
import QualityAssigneePicker from '@/components/QualityAssigneePicker.vue'
import TaskBoardActions from '@/components/TaskBoardActions.vue'
import TaskBoardStage from '@/components/TaskBoardStage.vue'
import WorkUnitApplications from '@/components/WorkUnitApplications.vue'
import {humanStep,modelStep} from '@/utils/taskBoardStages'
import {boardDialog,employeeInbox,listLocation} from '@/utils/taskBoardNavigation'
import {needsDetectionBatch} from '@/utils/workUnitApplications'
import {mutationHeaders} from '@/utils/mutationVersion'
import {useUserStore} from '@/stores/user'
const TaskDialogs=defineAsyncComponent(()=>import('./ImageDetection.vue'))
const employeeScopes=[{value:true,label:'待我处理'},{value:false,label:'全部任务'}]
const user=useUserStore(),supervisor=computed(()=>user.role==='SUPERVISOR'),api=captureAccountRequest()
const router=useRouter(),route=useRoute()
const uploadScope=computed(()=>route.meta.uploadScope)
const awaitingDispatch=computed(()=>Boolean(route.meta.awaitingDispatch))
const applicationId=computed(()=>supervisor.value && awaitingDispatch.value && typeof route.query.application==='string' ? route.query.application : '')
const application=ref(null),applicationError=ref('')
const uploadsOnly=computed(()=>Boolean(uploadScope.value))
const boardTitle=computed(()=>supervisor.value ? '任务总表' : '我的任务')
const taskList=computed(()=>route.meta.taskList)
const verificationList=computed(()=>taskList.value==='verification')
const inbox=computed(()=>!uploadsOnly.value && !supervisor.value && employeeInbox(route.query))
const inboxKind=computed(()=>inbox.value && ['detection','verification'].includes(route.query.kind) ? route.query.kind : undefined)
const inboxTitle=computed(()=>({detection:'待我检测',verification:'待我校验'})[inboxKind.value])
const directory=computed(()=>typeof route.query.directory==='string' ? route.query.directory : '')
const phases={'':'全部',READY:'未开始',DETECTING:'检测中',VERIFYING:'校验环节',DONE:'校验完成',FAILED:'异常',MODEL_DONE:'仅有检测结果'}
const detectionPhases={'':'全部',UPLOADING:'待上传确认',READY:'待检测',DETECTING:'检测中',FAILED:'检测失败',CANCELLED:'已取消',MODEL_DONE:'已检测'}
const inboxPhases={'':'全部待办',READY:'待启动检测',FAILED:'待重试检测',VERIFYING:'待核对结果'}
const verificationPhases={'':'全部',WAITING_CHECK:'待校验',VERIFYING:'校验中',CHECKED:'已校验',FOLLOW_UP:'待跟进'}
const pendingDetectionPhases={'':'全部待检测',READY:'待启动',FAILED:'待重试'}
const listPhases=computed(()=>inboxKind.value==='verification' ? {} : inboxKind.value==='detection' ? pendingDetectionPhases : verificationList.value ? verificationPhases : taskList.value==='detection' ? detectionPhases : inbox.value ? inboxPhases : phases)
const phase=computed(()=>Object.hasOwn(listPhases.value,route.query.phase) ? route.query.phase : '')
const keyword=computed(()=>typeof route.query.keyword==='string' ? route.query.keyword : '')
const assignedTaskId=computed(()=>!uploadsOnly.value && typeof route.query.assignedTaskId==='string' ? route.query.assignedTaskId : '')
const applicationKeyword=computed(()=>keyword.value.startsWith('WU-') ? keyword.value : '')
const showApplications=computed(()=>user.isAuthenticated && user.role==='INSPECTOR' && !uploadsOnly.value && !assignedTaskId.value
  && (inboxKind.value==='detection' || (!inboxKind.value && (!keyword.value || applicationKeyword.value))))
const page=computed(()=>Number.isSafeInteger(Number(route.query.page)) && Number(route.query.page)>0 ? Number(route.query.page) : 1)
const query=ref(''),uploaderInput=ref(''),total=ref(0),rows=ref([]),loading=ref(false),error=ref('')
const boardIcon=computed(()=>uploadsOnly.value ? 'FolderOpened' : verificationList.value || inboxKind.value==='verification' ? 'CircleCheck' : 'Tickets')
const emptyMessage=computed(()=>{
  if(awaitingDispatch.value)return '没有符合条件的待派文件夹。'
  if(inbox.value && !keyword.value && !phase.value) {
    return { detection:'当前没有待你启动或重试的检测。', verification:'当前没有分派给你的待校验结果。' }[inboxKind.value] || '当前没有待你处理的任务。'
  }
  if(uploadsOnly.value && uploadScope.value==='mine' && !keyword.value && !phase.value)return '你还没有上传记录。'
  return uploadsOnly.value ? '没有符合条件的上传记录。' : '当前筛选下没有任务。'
})
const dialog=ref(false),target=ref(null),recipient=ref({}),busy=ref(false),saveError=ref(''),requestId=ref('')
const sourceUpload=ref(null)
const folder=ref('detection/'),pathInput=ref(''),children=ref([]),next=ref(null),folderImages=ref(0),folderError=ref(''),browsing=ref(false),ready=ref(false)
const editingPath=ref(false)
const canSubmit=computed(()=>applicationId.value ? Boolean(application.value && sourceUpload.value) :
  Boolean(recipient.value.userId && (target.value || sourceUpload.value || (ready.value && folderImages.value && folder.value===pathInput.value))))
const folderChoices=computed(()=>{
  const counts=new Map()
  const choices=children.value.map(path=>{
    const leaf=path.slice(folder.value.length,-1)
    const label=path.endsWith('/Original/images/') ? '图片' : (/^originals?$/i.test(leaf) ? '原图' : imageFolderLabel(path))
    counts.set(label,(counts.get(label) || 0)+1)
    return {path,label,leaf}
  })
  return choices.map(({path,label,leaf})=>{
    if(counts.get(label)===1)return {path,label}
    const suffix=leaf.match(/_det_(\d{8}_\d{6}_[a-f0-9]{8})$/i)
    return {path,label:suffix ? label+' · '+suffix[1] : leaf}
  })
})
const parentFolder=computed(()=>folder.value.replace(/[^/]+\/$/,''))
let read=0,folderRead=0,timer
const url='/api/detection/board'
function data(response){if(response.data?.code!==200)throw Error(response.data?.message || '操作失败');return response.data.data}
const message=e=>e.response?.data?.message || e.message || '操作失败，请重试'
async function load(quiet=false){
  const generation=++read
  if(!quiet)loading.value=true
  try{
    const params={page:page.value,size:20,keyword:keyword.value,phase:phase.value}
    if(uploadsOnly.value){
      params.scope=uploadScope.value
      if(awaitingDispatch.value)params.awaitingDispatch=true
      if(uploadScope.value==='team' && typeof route.query.uploader==='string')params.uploader=route.query.uploader
    } else {
      params.inbox=inbox.value
      params.inboxKind=inboxKind.value
      params.directory=directory.value || undefined
      params.assignedTaskId=assignedTaskId.value || undefined
      params.taskList=taskList.value
    }
    const result=data(await api.get(uploadsOnly.value ? url+'/uploads' : url,{params}))
    if(generation!==read)return
    const lastPage=Math.max(1,Math.ceil(result.total/20))
    if(!activeAction.value && page.value>lastPage){
      const scope=!uploadsOnly.value && !supervisor.value ? {inbox:inbox.value ? '1' : '0'} : {}
      await router.replace({path:route.path,query:{...route.query,...scope,page:lastPage===1 ? undefined : String(lastPage)}})
      return
    }
    rows.value=result.items;total.value=result.total;error.value=''
  }catch(e){if(generation===read)error.value=message(e)}finally{if(generation===read)loading.value=false}
}
function changeFilters(values){
  const scope=!uploadsOnly.value && !supervisor.value ? {inbox:inbox.value ? '1' : '0'} : {}
  return router.push({path:route.path,query:{...route.query,...scope,...values}})
}
function employeeScopeLink(pending){return {path:'/inspection/tasks',query:{inbox:pending ? '1' : '0'}}}
function filter(key){changeFilters({phase:key || undefined,page:undefined})}
function searchColleague(){
  const uploader=uploaderInput.value.trim()
  if(!uploader)return
  if(uploader===user.username){
    uploaderInput.value=''
    return router.push({path:'/inspection/uploads/mine'})
  }
  return router.push({path:'/inspection/uploads/all',query:{uploader}})
}
function search(){changeFilters({keyword:query.value.trim() || undefined,assignedTaskId:undefined,uploader:uploadsOnly.value && uploadScope.value==='team' ? uploaderInput.value.trim() || undefined : undefined,page:undefined})}
function turn(value){if(value!==page.value)changeFilters({page:value===1 ? undefined : String(value)})}
const isOssFolder=row=>row.prefix?.startsWith('detection/') && row.prefix.endsWith('/')
function previewTaskId(row){return Number(row.canReadTask) ? row.taskId : row.myDetectionTaskId}
function dispatchUnavailable(row){
  if(row.taskType==='SINGLE')return '单图检测'
  if(Number(row.uploadPending))return '等待上传确认'
  if(!isOssFolder(row))return '未关联可派发的原图目录'
  if(applicationId.value && !application.value)return '请先读取检测申请'
  if(application.value && row.totalImages>application.value.imageCount)return '超过申请的图片数量'
  return ''
}
function rowActions(row) {
  return {
    row, actionLink, previewTaskId: previewTaskId(row), dispatchReason: uploadsOnly.value && supervisor.value ? dispatchUnavailable(row) : '',
    supervisor: supervisor.value, username: user.username, taskList: taskList.value, applicationId: applicationId.value,
    uploadsOnly: uploadsOnly.value, awaitingDispatch: awaitingDispatch.value, busy: busy.value
  }
}
function togglePath(){
  pathInput.value=folder.value
  editingPath.value=!editingPath.value
}
const activeAction=computed(()=>boardDialog(route.query,supervisor.value,uploadsOnly.value))
const listPath=computed(()=>router.resolve(listLocation(route)).fullPath)
function actionLink(taskId,action){
  return {path:route.path,query:{...route.query,taskId,boardAction:action},hash:route.hash}
}
function closeAction(){
  if(!activeAction.value)return
  if(router.options.history.state.back===listPath.value)router.back()
  else router.replace(listLocation(route))
}
watch(activeAction,(current,previous)=>{
  if(!current && previous && (uploadsOnly.value || taskList.value || route.name==='folderTaskBoard'))load(true)
})
function openNew({prefix='',upload=null}={}){
  if(upload && dispatchUnavailable(upload))return
  sourceUpload.value=upload
  editingPath.value=false
  target.value=null;recipient.value={};requestId.value=crypto.randomUUID();saveError.value='';dialog.value=true
  if(!upload)browse(prefix)
}
function openAssign(row){sourceUpload.value=null;target.value=row;recipient.value={};saveError.value='';dialog.value=true}
async function browse(value,marker){
  const generation=++folderRead
  const path=value.trim() ? value.trim().replace(/\/?$/,'/') : ''
  if(!marker){pathInput.value=path;folder.value=path;children.value=[];folderImages.value=0;next.value=null}
  browsing.value=true;ready.value=false;folderError.value=''
  try{const result=data(await api.get(url+'/folders',{params:{prefix:path || undefined,marker}}));if(generation!==folderRead)return
    if(!marker){folder.value=result.prefix;pathInput.value=result.prefix;editingPath.value=false}
    children.value.push(...result.folders);next.value=result.next;folderImages.value+=result.imagesOnPage;ready.value=true
  }catch(e){if(generation===folderRead)folderError.value=message(e)}finally{if(generation===folderRead)browsing.value=false}
}
async function save(){
  if(busy.value || !canSubmit.value)return
  busy.value=true;saveError.value=''
  try{
    let taskId=target.value?.taskId
    if(applicationId.value){
      taskId=data(await api.post(url+'/applications/'+encodeURIComponent(applicationId.value)+'/dispatch',{
        uploadTaskId:sourceUpload.value.taskId,expectedVersion:application.value.version
      },{timeout:60000}))
    }else if(taskId)data(await api.post(url+'/'+taskId+'/assign',{version:target.value.assignmentVersion,recipient:recipient.value}))
    else taskId=data(await api.post(url,{requestId:requestId.value,prefix:sourceUpload.value?.prefix ?? folder.value,recipient:recipient.value},{timeout:60000}))
    const assignedName=application.value?.applicantUserId || recipient.value.username
    dialog.value=false;ElMessage.success('检测任务已派发给 '+assignedName)
    const destination={path:'/inspection/tasks/detection',query:{keyword:taskId}}
    if(router.resolve(destination).fullPath===route.fullPath)await load()
    else await router.push(destination)
  }catch(e){saveError.value=message(e)}finally{busy.value=false}
}
async function start(row){
  if(busy.value)return
  busy.value=true
  const origin=route.fullPath
  try {
    data(await api.post(url+'/'+row.taskId+'/start',null,{params:{version:row.assignmentVersion}}))
    if(route.fullPath!==origin)return
    ElMessage.success('模型检测已提交')
    if(inbox.value)await router.push({path:'/inspection/tasks',query:{inbox:'0',assignedTaskId:row.taskId}})
    else await load()
  }
  catch(e){ElMessage.error(message(e));await load()}finally{busy.value=false}
}
async function startRecheck(row){
  if(busy.value)return
  busy.value=true
  const origin=route.fullPath
  try {
    await ElMessageBox.confirm('将沿用此任务的原图和检测参数重新检测，当前检测结果、校验结论和处置状态将重置。', '启动复检', {
      confirmButtonText:'确认启动复检', cancelButtonText:'取消', type:'warning'
    })
    if(route.fullPath!==origin)return
    data(await api.post('/api/detection/tasks/'+encodeURIComponent(row.taskId)+'/retry',null,{headers:mutationHeaders(row.mutationVersion)}))
    ElMessage.success('复检已提交')
    if(route.fullPath===origin)await load()
  }catch(e){
    if(e==='cancel'||e==='close')return
    ElMessage.error(message(e))
    if(route.fullPath===origin)await load()
  }finally{busy.value=false}
}
watch(applicationId,async (id,_,onCleanup)=>{
  application.value=null;applicationError.value=''
  if(!id)return
  let stale=false
  onCleanup(()=>{stale=true})
  try {
    const list=data(await api.get('/api/detection/supervisor/work-units/pending'))
    if(stale)return
    application.value=list.find(row=>row.workUnitId===id && needsDetectionBatch(row)) || null
    if(!application.value)applicationError.value='申请已处理或已变化，请返回工作台核对。'
  }catch{
    if(!stale)applicationError.value='申请暂不可读取，请刷新页面重试。'
  }
},{immediate:true})
watch(listPath,()=>{
  if(route.name!=='folderTaskBoard' && !uploadsOnly.value && !taskList.value)return
  query.value=assignedTaskId.value || keyword.value;uploaderInput.value=uploadScope.value==='team' && typeof route.query.uploader==='string' ? route.query.uploader : ''
  dialog.value=false;rows.value=[];total.value=0;error.value='';load()
},{immediate:true})
onMounted(()=>{timer=setInterval(()=>{if(!document.hidden&&!dialog.value&&!activeAction.value&&!busy.value&&!loading.value)load(true)},6000)})
watch(()=>user.accountContext,()=>{read++;folderRead++;rows.value=[];total.value=0;dialog.value=false})
onBeforeUnmount(()=>{clearInterval(timer);read++;folderRead++})
</script>
<style scoped>
.task-board {
  display:grid; gap:14px; min-width:0; color:var(--app-text);
  container:inspection-board / inline-size;
}
.board-heading,.board-title,.board-links,.board-links a {
  display:flex; align-items:center; gap:10px;
}
.board-heading { justify-content:space-between; flex-wrap:wrap; min-height:44px; }
.board-title { min-width:0; }
.board-heading h1 { margin:0; font-size:clamp(23px, 2vw, 29px); font-weight:700; line-height:1.25; }
.board-mark {
  display:grid; place-items:center; flex:0 0 38px; height:38px; border-radius:8px;
  background:var(--app-primary-soft); color:var(--app-primary);
}
.board-links { flex-wrap:wrap; }
.board-links a { min-height:36px; color:var(--app-primary); text-decoration:none; font-size:13px; }
.board-links a:hover { text-decoration:underline; }
.board-flow { padding:5px 8px; }
.board-flow :deep(.flow-steps) { grid-template-columns:repeat(4,minmax(0,1fr)); gap:4px; }
.board-flow :deep(.flow-steps a) { min-height:44px; padding:6px 9px; }
.board-flow :deep(.step-icon) { width:28px; height:28px; }

.board-panel { min-width:0; overflow:hidden; border:1px solid var(--app-border); border-radius:12px; background:var(--app-surface); }
.upload-navigation {
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:0 16px;
  padding:0 16px; border-bottom:1px solid var(--app-border);
}
.upload-scopes { display:flex; flex-wrap:wrap; gap:8px 16px; }
.upload-scopes a {
  display:inline-flex; align-items:center; min-height:44px; padding:0 4px; border-bottom:2px solid transparent;
  text-decoration:none; color:var(--app-text-secondary); font-size:14px; font-weight:600;
}
.upload-scopes a[aria-current=page] { border-color:var(--app-primary); color:var(--app-primary); }
.colleague-search { display:flex; align-items:center; gap:8px; width:min(100%,290px); padding:5px 0; }
.colleague-search .el-input { min-width:0; }
.directory-filter {
  display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:10px 15px;
  background:var(--app-primary-soft); overflow-wrap:anywhere; font-size:13px;
}
.board-toolbar {
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap;
  gap:10px 16px; padding:12px 15px; border-bottom:1px solid var(--app-border);
}
.phases { display:flex; flex-wrap:wrap; gap:3px; }
.phases button {
  min-height:36px; padding:0 10px; border:0; border-radius:6px; cursor:pointer;
  background:transparent; color:var(--app-text-secondary); font:inherit; font-size:13px;
}
.phases button:hover { background:var(--app-surface-muted); color:var(--app-primary); }
.phases button[aria-pressed=true] { background:var(--app-primary-soft); color:var(--app-primary); font-weight:650; }
.task-search { display:flex; flex:0 1 284px; gap:8px; max-width:100%; margin-left:auto; }
.task-search :deep(.el-input) { min-width:0; }
.task-search:has(input[aria-label="上传人工号"]) { flex-basis:450px; }
.task-search :deep(.el-button) { flex:none; }
.board-error {
  display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:10px 16px;
  background:var(--app-warning-soft); color:var(--app-warning); font-size:13px; overflow-wrap:anywhere;
}
.board-error span { flex:1 1 145px; }
.board-empty { display:grid; justify-items:center; gap:6px; padding:28px 16px; color:var(--app-text-secondary); text-align:center; }
.board-empty:empty { min-height:90px; }
.board-results[aria-busy=false] .board-empty:empty { display:none; }
.board-empty p { margin:0; }
.board-empty a { display:inline-flex; align-items:center; min-height:40px; color:var(--app-primary); text-decoration:none; }

.board-table :deep(th.el-table__cell) { background:var(--app-surface-muted); font-size:12px; }
.board-table :deep(td.el-table__cell) { padding:10px 0; }
.board-table :deep(.el-table__cell .cell) { padding-inline:14px; }
.board-panel small { color:var(--app-text-secondary); font-size:12px; line-height:1.55; }
.board-table small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.folder-name { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.folder-metadata {
  display:flex; align-items:center; gap:0 12px; flex-wrap:wrap; margin-top:1px;
  color:var(--app-text-secondary); font-size:12px;
}
.person-label { color:var(--app-text-secondary); }
.board-table progress { display:block; width:min(100%,126px); height:6px; margin-top:4px; accent-color:var(--app-primary); }
.board-cards { display:none; }
.board-panel footer {
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:6px;
  padding:10px 15px; border-top:1px solid var(--app-border); color:var(--app-text-secondary); font-size:12px;
}

.application-dispatch {
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px 20px; padding:12px 16px;
  border:1px solid var(--app-border); border-radius:12px; background:var(--app-primary-soft); overflow-wrap:anywhere;
}
.application-dispatch p { margin:4px 0; color:var(--app-text-secondary); font-size:13px; }
.application-dispatch a { display:inline-flex; align-items:center; min-height:44px; color:var(--app-primary); }
.folder-field,.path-bar,.folder-children { width:100%; }
.path-bar,.folder-status { display:flex; align-items:center; gap:8px; }
.folder-status { flex-wrap:wrap; margin:8px 0; color:var(--app-text-secondary); font-size:12px; overflow-wrap:anywhere; }
.folder-status strong { color:var(--app-text); }
.folder-status button:last-child { margin-left:auto; }
.folder-status button,.folder-children button { border:0; background:transparent; color:var(--app-primary); cursor:pointer; font:inherit; }
.folder-children {
  display:grid; max-height:190px; overflow:auto; min-height:36px; padding:6px; border-radius:6px;
  background:var(--app-surface-muted);
}
.folder-children button { display:flex; align-items:center; gap:7px; min-height:36px; padding:5px; text-align:left; }
.folder-children span,.picked-folder-metadata { font-size:12px; }
.picked-folder-metadata summary { color:var(--app-primary); cursor:pointer; }
.picked-folder-metadata dd { margin:3px 0; overflow-wrap:anywhere; }
.board-heading a:focus-visible,.upload-scopes a:focus-visible,.phases button:focus-visible,.board-empty a:focus-visible {
  outline:2px solid var(--app-primary); outline-offset:2px;
}

@container inspection-board (max-width: 910px) {
  .board-table { display:none; }
  .board-cards {
    display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px;
    margin:0; padding:13px; list-style:none; background:var(--app-surface-muted);
  }
  .board-card { min-width:0; padding:12px 14px 8px; border-radius:9px; background:var(--app-surface); }
  .board-card-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:8px; }
  .board-card-heading > div { min-width:0; }
  .board-card-heading h2 { margin:0 0 2px; overflow-wrap:anywhere; font-size:15px; line-height:1.45; }
  .board-card-heading :deep(.metadata-link) { flex:none; }
  .card-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin:10px 0 0; }
  .card-facts dt { color:var(--app-text-secondary); font-size:12px; line-height:1.5; }
  .card-facts dd { margin:3px 0 0; overflow-wrap:anywhere; font-size:13px; }
  .board-card-actions { margin-top:8px; padding-top:6px; border-top:1px solid var(--app-border); }
}
@container inspection-board (max-width: 560px) {
  .board-flow :deep(.flow-steps) { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .board-toolbar { padding:9px 11px; gap:6px; }
  .task-search,.task-search:has(input[aria-label="上传人工号"]) { flex-basis:100%; margin:0; }
  .task-search:has(input[aria-label="上传人工号"]) { flex-wrap:wrap; }
  .task-search:has(input[aria-label="上传人工号"]) :deep(.el-input) { flex:1 1 112px; }
  .upload-navigation { padding-inline:11px; }
  .board-cards { grid-template-columns:minmax(0,1fr); padding:9px; }
  .board-card { padding-inline:12px; }
  .board-panel footer { padding-inline:11px; }
}
@media (pointer:coarse), (max-width:600px) {
  .board-heading .el-button,.board-heading a,.task-search :deep(.el-button),.task-search :deep(.el-input__wrapper),.phases button {
    min-height:44px;
  }
  .task-search :deep(input),.colleague-search :deep(input) { font-size:16px; }
  .board-card-heading :deep(.metadata-link) { min-height:44px; }
}
</style>
