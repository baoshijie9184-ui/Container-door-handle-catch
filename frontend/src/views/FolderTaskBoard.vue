<template>
  <main class="task-board">
    <header class="board-heading"><div><h1>{{ uploadsOnly || taskList ? route.meta.title : boardTitle }}</h1></div>
      <nav class="board-links" aria-label="相关操作">
        <router-link v-if="uploadsOnly" to="/upload"><AppIcon name="Upload" :size="16"/>上传图片</router-link>
        <router-link v-if="uploadsOnly" to="/inspection/tasks"><AppIcon name="Tickets" :size="16"/>{{ boardTitle }}</router-link>
        <router-link v-else-if="supervisor" to="/inspection/uploads/all"><AppIcon name="FolderOpened" :size="16"/>全部上传记录</router-link>
        <router-link v-else to="/inspection/uploads/mine"><AppIcon name="FolderOpened" :size="16"/>我的上传记录</router-link>
        <el-button v-if="supervisor && !uploadsOnly && !verificationList" type="primary" @click="openNew()"><AppIcon name="Plus"/>新建文件夹任务</el-button>
      </nav>
    </header>
    <section class="board-panel" aria-label="任务列表">
      <div v-if="supervisor && !uploadsOnly" class="upload-navigation">
        <nav class="upload-scopes" aria-label="主管任务列表">
          <router-link to="/inspection/tasks/detection">检测任务列表</router-link>
          <router-link to="/inspection/tasks/verification">校验任务列表</router-link>
          <router-link to="/inspection/tasks">任务总表</router-link>
        </nav>
      </div>
      <div v-if="uploadsOnly" class="upload-navigation">
        <nav class="upload-scopes" aria-label="上传记录范围">
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
      <div class="board-toolbar"><div v-if="!uploadsOnly || supervisor || uploadScope==='mine'" class="phases" aria-label="按任务阶段筛选">
        <button v-for="(label,key) in listPhases" :key="key" :aria-pressed="phase===key" @click="filter(key)">{{ label }}</button>
      </div><form @submit.prevent="search">
        <el-input v-if="uploadsOnly && uploadScope==='team'" v-model="uploaderInput" maxlength="50" placeholder="上传人工号" aria-label="上传人工号" clearable @clear="search"/>
        <el-input v-model="query" maxlength="255" :placeholder="uploadsOnly ? '搜文件夹或任务号' : '搜目录、任务或工号'" aria-label="搜索任务" clearable @clear="search"/>
        <el-button native-type="submit">查询</el-button>
      </form></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <el-table :data="rows" v-loading="loading" row-key="taskId" empty-text="当前筛选下没有任务">
        <template #empty><span v-if="loading">正在读取…</span><span v-else-if="error">记录暂不可读取</span><template v-else-if="uploadsOnly && uploadScope==='mine' && !keyword && !phase">你还没有上传记录。<router-link to="/inspection/uploads/all">查看全部上传</router-link></template><template v-else-if="inbox && !keyword && !phase">当前没有待你处理的任务。<router-link :to="employeeScopeLink(false)">查看全部任务</router-link></template><template v-else-if="taskList==='detection' && keyword">当前没有符合条件的检测任务。<router-link :to="{path:'/inspection/tasks/verification',query:{keyword}}">在校验列表查找</router-link></template><span v-else>{{ uploadsOnly ? '没有符合条件的上传记录' : '当前筛选下没有任务' }}</span></template>
        <el-table-column label="图片文件夹" min-width="195"><template #default="{row}">
          <strong class="folder-name" :title="recordFolderLabel(row)">{{ recordFolderLabel(row) }}</strong>
          <div v-if="uploadsOnly" class="folder-metadata">
            <span>{{ row.totalImages ?? '—' }} 张图片</span>
            <details><summary>任务号</summary><code>{{ row.taskId }}</code></details>
          </div>
        </template></el-table-column>
        <el-table-column v-if="uploadsOnly" label="上传人" min-width="150"><template #default="{row}">
          <div><span class="person-label">工号：</span>{{ row.creator || '未关联' }}</div>
          <div><span class="person-label">姓名：</span>{{ row.creatorName || '—' }}</div>
        </template></el-table-column>
        <el-table-column v-if="uploadsOnly" label="登记时间" min-width="155"><template #default="{row}">
          {{ row.registeredAt || '—' }}
        </template></el-table-column>
        <el-table-column v-if="uploadsOnly" label="记录状态" min-width="145"><template #default="{row}">
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
          <strong class="phase" :data-phase="row.modelStatus">{{ modelStep(row) }}</strong>
          <small v-if="row.totalImages != null">已处理 {{ row.processedImages ?? '—' }} / {{ row.totalImages }} 张<span v-if="row.failedImages"> · {{ row.failedImages }} 张失败</span></small>
          <progress v-if="row.totalImages && ['QUEUED','DETECTING','RUNNING'].includes(row.modelStatus)" :value="row.processedImages" :max="row.totalImages" aria-label="模型图片处理进度"/>
          <small v-if="!taskList && (row.detectionOperator || row.detector)">{{ row.detectionOperator ? '执行工号' : '受派工号' }} {{ row.detectionOperator || row.detector }}</small>
        </template></el-table-column>
        <el-table-column v-if="!uploadsOnly && taskList!=='detection'" label="人工校验" min-width="145"><template #default="{row}">
          <strong class="phase" :data-phase="row.listPhase">{{ humanStep(row) }}</strong>
          <small v-if="!taskList && (row.qualityOperator || row.qualityAssignee)">{{ row.qualityOperator ? '校验工号' : '受派工号' }} {{ row.qualityOperator || row.qualityAssignee }}</small>
        </template></el-table-column>
        <el-table-column v-if="taskList==='detection'" label="检测员工" min-width="126"><template #default="{row}">{{ row.detectionOperator || row.detector || '—' }}<small v-if="row.detector">{{ row.detectionOperator ? '已执行检测' : '受派检测' }}</small></template></el-table-column>
        <el-table-column v-if="verificationList" label="校验员工" min-width="126"><template #default="{row}">{{ row.qualityOperator || row.qualityAssignee || '—' }}<small v-if="row.qualityOperator || row.qualityAssignee">{{ row.reviewedAt ? '已提交校验' : '受派校验' }}</small></template></el-table-column>
        <el-table-column label="操作" min-width="245"><template #default="{row}">
          <div class="row-actions">
            <template v-if="uploadsOnly">
              <router-link v-if="previewTaskId(row)" :to="actionLink(previewTaskId(row), 'images')">查看原图</router-link>
              <el-button v-else link disabled>查看原图</el-button>
              <template v-if="supervisor">
                <el-button size="small" type="primary" :disabled="Boolean(dispatchUnavailable(row))" @click="openNew({ upload: row })">派发检测任务</el-button>
                <small v-if="dispatchUnavailable(row)" class="dispatch-reason">{{ dispatchUnavailable(row) }}</small>
              </template>
              <template v-else>
                <el-button size="small" type="primary" :disabled="Boolean(detectionUnavailable(row))"
                  @click="router.push({ path:'/inspection/tasks', query:{ assignedTaskId:row.myDetectionTaskId } })">去完成检测任务</el-button>
                <small v-if="detectionUnavailable(row)" class="dispatch-reason">{{ detectionUnavailable(row) }}</small>
              </template>
            </template>
            <template v-else>
            <el-button v-if="Number(row.mine) && ['READY','FAILED'].includes(row.modelStatus)" size="small" type="primary" @click="start(row)" :disabled="busy">{{ row.modelStatus==='FAILED'?'重试模型检测':'启动模型检测' }}</el-button>
            <el-button v-if="supervisor && row.taskType==='OSS_FOLDER' && row.phase==='READY'" size="small" @click="openAssign(row)">改派检测</el-button>
            <template v-if="canReview(row)">
              <router-link v-if="supervisor && !row.qualityAssignee" class="next-action" :to="actionLink(row.taskId,'assign')">分派校验任务</router-link>
              <router-link v-if="supervisor || row.qualityAssignee===user.username" :class="{ 'next-action': !!row.qualityAssignee }" :to="actionLink(row.taskId,'review')">核对模型结果</router-link>
              <router-link v-if="supervisor && row.qualityAssignee" :to="actionLink(row.taskId,'assign')">改派校验</router-link>
            </template>
            <router-link :to="actionLink(row.taskId,'trace')">任务详情</router-link>
            <button v-if="taskList==='detection' && row.taskType!=='OSS_FOLDER' && row.modelStatus!=='UPLOADING' && isOssFolder(row)" @click="openNew({ upload:row })">派发检测任务</button>
            <button v-else-if="supervisor && !taskList && isOssFolder(row)" @click="openNew({ prefix: row.prefix })">以此目录派单</button>
            </template>
          </div>
        </template></el-table-column>
      </el-table>
      <footer><span>{{ loading ? '正在读取…' : '共 '+total+' 项' }}</span><el-pagination v-if="total>20" layout="prev, pager, next" :pager-count="5" :page-size="20" :total="total" :current-page="page" @current-change="turn"/></footer>
    </section>
    <TaskDialogs v-if="activeAction" :key="activeAction.action + ':' + activeAction.taskId" :board-request="activeAction" @dismiss="closeAction" />
    <el-dialog v-model="dialog" :title="target ? '改派检测员工' : sourceUpload ? '派发检测任务' : '新建文件夹任务'" width="min(620px, 95vw)" destroy-on-close :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy">
      <el-form label-position="top" @submit.prevent>
        <el-form-item v-if="sourceUpload" label="原图文件夹">
          <strong>{{ recordFolderLabel(sourceUpload) }}</strong>
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
            <el-alert v-if="folderError" type="error" :title="folderError" :closable="false"/>
          </div>
        </el-form-item>
        <el-form-item label="检测员工工号"><QualityAssigneePicker v-model="recipient.username" v-model:user-id="recipient.userId" v-model:revision="recipient.revision" account-label="检测员工工号" :disabled="busy"/></el-form-item>
        <el-alert v-if="saveError" type="error" :title="saveError" :closable="false"/>
      </el-form>
      <template #footer><el-button :disabled="busy" @click="dialog=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="!canSubmit" @click="save">确认派发</el-button></template>
    </el-dialog>
  </main>
</template>
<script setup>
import {computed,defineAsyncComponent,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {ElMessage} from 'element-plus'
import {captureAccountRequest} from '@/api/request'
import {imageFolderLabel,recordFolderLabel} from '@/utils/imageFolderLabel'
import QualityAssigneePicker from '@/components/QualityAssigneePicker.vue'
import {humanStep,modelStep,canReview} from '@/utils/taskBoardStages'
import {boardDialog,employeeInbox,listLocation} from '@/utils/taskBoardNavigation'
import {useUserStore} from '@/stores/user'
const TaskDialogs=defineAsyncComponent(()=>import('./ImageDetection.vue'))
const employeeScopes=[{value:true,label:'待我处理'},{value:false,label:'全部任务'}]
const user=useUserStore(),supervisor=computed(()=>user.role==='SUPERVISOR'),api=captureAccountRequest()
const router=useRouter(),route=useRoute()
const uploadScope=computed(()=>route.meta.uploadScope)
const uploadsOnly=computed(()=>Boolean(uploadScope.value))
const boardTitle=computed(()=>supervisor.value ? '任务总表' : '我的任务')
const taskList=computed(()=>route.meta.taskList)
const verificationList=computed(()=>taskList.value==='verification')
const inbox=computed(()=>!uploadsOnly.value && !supervisor.value && employeeInbox(route.query))
const directory=computed(()=>typeof route.query.directory==='string' ? route.query.directory : '')
const phases={'':'全部',READY:'未开始',DETECTING:'检测中',VERIFYING:'校验环节',DONE:'校验完成',FAILED:'异常',MODEL_DONE:'仅有检测结果'}
const detectionPhases={'':'全部',UPLOADING:'待上传确认',READY:'待检测',DETECTING:'检测中',FAILED:'检测失败',CANCELLED:'已取消',MODEL_DONE:'已检测'}
const inboxPhases={'':'全部待办',READY:'待启动检测',FAILED:'待重试检测',VERIFYING:'待核对结果'}
const verificationPhases={'':'全部',WAITING_CHECK:'待校验',VERIFYING:'校验中',CHECKED:'已校验',FOLLOW_UP:'待跟进'}
const listPhases=computed(()=>verificationList.value ? verificationPhases : taskList.value==='detection' ? detectionPhases : inbox.value ? inboxPhases : phases)
const phase=computed(()=>Object.hasOwn(listPhases.value,route.query.phase) ? route.query.phase : '')
const keyword=computed(()=>typeof route.query.keyword==='string' ? route.query.keyword : '')
const assignedTaskId=computed(()=>!uploadsOnly.value && typeof route.query.assignedTaskId==='string' ? route.query.assignedTaskId : '')
const page=computed(()=>Number.isSafeInteger(Number(route.query.page)) && Number(route.query.page)>0 ? Number(route.query.page) : 1)
const query=ref(''),uploaderInput=ref(''),total=ref(0),rows=ref([]),loading=ref(false),error=ref('')
const dialog=ref(false),target=ref(null),recipient=ref({}),busy=ref(false),saveError=ref(''),requestId=ref('')
const sourceUpload=ref(null)
const folder=ref('detection/'),pathInput=ref(''),children=ref([]),next=ref(null),folderImages=ref(0),folderError=ref(''),browsing=ref(false),ready=ref(false)
const editingPath=ref(false)
const canSubmit=computed(()=>Boolean(recipient.value.userId && (target.value || sourceUpload.value || (ready.value && folderImages.value && folder.value===pathInput.value))))
const folderChoices=computed(()=>{
  const counts=new Map()
  const choices=children.value.map(path=>{
    const leaf=path.slice(folder.value.length,-1)
    const label=/^originals?$/i.test(leaf) ? '原图' : imageFolderLabel(path)
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
      if(uploadScope.value==='team' && typeof route.query.uploader==='string')params.uploader=route.query.uploader
    } else {
      params.inbox=inbox.value
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
function detectionUnavailable(row){
  if(!row.myDetectionTaskId)return '未分派给我'
  if(row.myDetectionStatus==='CANCELLED')return '检测任务已取消'
  if(['COMPLETED','PARTIAL_FAILED'].includes(row.myDetectionStatus))return '本次模型检测已结束'
  return ''
}
function dispatchUnavailable(row){
  if(Number(row.uploadPending))return '等待上传确认'
  if(!isOssFolder(row))return '未关联可派发的原图目录'
  return ''
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
    if(taskId)data(await api.post(url+'/'+taskId+'/assign',{version:target.value.assignmentVersion,recipient:recipient.value}))
    else taskId=data(await api.post(url,{requestId:requestId.value,prefix:sourceUpload.value?.prefix ?? folder.value,recipient:recipient.value},{timeout:60000}))
    dialog.value=false;ElMessage.success('检测任务已派发给 '+recipient.value.username)
    const destination={path:'/inspection/tasks/detection',query:{keyword:taskId}}
    if(router.resolve(destination).fullPath===route.fullPath)await load()
    else await router.push(destination)
  }catch(e){saveError.value=message(e)}finally{busy.value=false}
}
async function start(row){
  if(busy.value)return
  busy.value=true
  try{data(await api.post(url+'/'+row.taskId+'/start',null,{params:{version:row.assignmentVersion}}));ElMessage.success('模型检测已提交');await load()}
  catch(e){ElMessage.error(message(e));await load()}finally{busy.value=false}
}
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
.person-label{color:var(--app-text-secondary)}
.row-actions .dispatch-reason{flex-basis:100%;white-space:normal}
.folder-name{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.folder-metadata{display:flex;align-items:baseline;flex-wrap:wrap;gap:0 12px;color:var(--app-text-secondary);font-size:12px}
.folder-metadata summary{cursor:pointer}.folder-metadata code{overflow-wrap:anywhere}
.folder-status strong{color:var(--app-text)}.folder-status button:last-child{margin-left:auto}
.upload-navigation{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:0 16px;padding:0 16px;border-bottom:1px solid var(--app-border)}
.upload-scopes{display:flex;gap:20px}.upload-scopes a{padding:13px 3px 10px;border-bottom:3px solid transparent;text-decoration:none;color:var(--app-text-secondary);font-weight:600}.upload-scopes a[aria-current=page]{border-color:var(--app-primary);color:var(--app-primary)}
.colleague-search{display:flex;align-items:center;gap:8px;width:290px;max-width:100%;padding:5px 0}.colleague-search .el-input{min-width:0}
.board-toolbar form:has(input[aria-label="上传人工号"]){flex:1 1 400px;max-width:620px;flex-wrap:wrap}.board-toolbar form:has(input[aria-label="上传人工号"]) .el-input{flex:1 1 165px}
.board-links,.board-links a,.directory-filter{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.board-links a{min-height:32px;padding:0 10px;color:var(--app-primary);text-decoration:none}.board-links a:hover,.row-actions a:hover{text-decoration:underline}.directory-filter{padding:12px 15px;background:var(--app-primary-soft);overflow-wrap:anywhere;font-size:13px}
.task-board{display:grid;gap:18px;color:var(--app-text);min-width:0}.board-heading,.board-toolbar,.board-panel footer,.path-bar,.folder-status,.row-actions,.phases,.board-toolbar form{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.board-heading,.board-toolbar,.board-panel footer{justify-content:space-between}.board-heading h1{margin:0;font-size:28px}.board-heading p,.folder-status,.board-panel small,.board-panel footer>span{color:var(--app-text-secondary);font-size:12px}.board-heading p{margin:6px 0 0}.board-panel{min-width:0;border:1px solid var(--app-border);border-radius:12px;background:white;overflow:hidden}.board-toolbar,.board-panel footer{padding:15px}.board-toolbar form{flex-wrap:nowrap;max-width:100%}.board-panel small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.phases{gap:3px}.phases button,.row-actions button:not(.el-button),.folder-status button,.folder-children button{border:0;cursor:pointer;background:transparent;color:var(--app-primary);font:inherit}.phases button{padding:7px 10px;border-radius:6px;color:var(--app-text-secondary)}.phases button[aria-pressed=true]{background:var(--app-primary-soft);color:var(--app-primary);font-weight:650}.phase{font-size:13px}.phase[data-phase=DETECTING],.phase[data-phase=DONE]{color:#2156af}.phase[data-phase=VERIFYING]{color:#895005}.phase[data-phase=FAILED]{color:#a53d32}.board-panel progress{display:block;height:5px;width:100px;max-width:100%;margin-top:5px;accent-color:#2866da}.row-actions{gap:7px 12px}.row-actions a,.row-actions button:not(.el-button){color:var(--app-primary);text-decoration:none;font-size:13px;padding:0}.folder-field,.path-bar,.folder-children{width:100%}.path-bar{flex-wrap:nowrap}.folder-status{margin:8px 0;overflow-wrap:anywhere;line-height:1.4}.folder-children{display:grid;max-height:190px;overflow:auto;background:var(--app-surface-muted);padding:6px;border-radius:6px;min-height:36px}.folder-children button{display:flex;align-items:center;gap:7px;padding:5px;text-align:left}.folder-children span{font-size:12px}.board-panel footer{border-top:1px solid var(--app-border)}
.row-actions a.next-action{display:inline-flex;align-items:center;min-height:28px;padding:0 9px;border-radius:5px;background:var(--app-primary-soft);color:var(--app-primary);font-weight:650}
.row-actions a:focus-visible,.upload-scopes a:focus-visible{outline:2px solid var(--app-primary);outline-offset:2px}
</style>
