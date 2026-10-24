<template>
  <div class="composer">
    <Transition name="slash-menu">
      <section v-if="menuVisible" ref="commandMenuRef" class="slash-menu" aria-label="技能命令建议">
        <p>方向键选择 · Enter 或 Tab 补全 · Escape 关闭</p>
        <div :id="commandListId" role="listbox" aria-label="技能命令">
          <button v-for="(item,index) in commandOptions" :id="commandListId+'-'+index" :key="item.value" type="button" role="option" tabindex="-1" :aria-selected="index===activeCommand" :class="{active:index===activeCommand}" @mousedown.prevent @click="selectCommand(item)"><strong>{{ item.label }}</strong><span>{{ item.description }}</span></button>
        </div>
      </section>
    </Transition>
    <p v-if="commandError && draft.startsWith('/')" class="command-error" role="status">{{ commandError }}</p>
    <!-- 快捷指令 chips -->
    <div class="quick-chips" v-if="!loading && showPresets">
      <button
        v-for="chip in quickChips"
        :key="chip.text"
        type="button"
        class="quick-chip"
        @click="sendPreset(chip.text)"
      >
        <AppIcon :name="chip.icon" :size="14" />
        {{ chip.label }}
      </button>
    </div>
    <slot name="queue" />
    <div class="composer-input-wrap gpt-composer-input">
      <TransitionGroup name="slash-menu" tag="div" class="composer-attachments" v-if="resources.files.length" role="list" aria-label="本条消息的附件引用">
        <div v-for="file in resources.files" :key="file.id" class="composer-attachment" role="listitem"><span class="composer-file-icon"><AppIcon :name="composerAttachment(file).icon" :size="18" /></span><span class="composer-file-copy"><strong :title="file.name">{{ file.name }}</strong><small>{{ composerAttachment(file).type }} · {{ composerAttachment(file).size }}</small></span><button type="button" :disabled="resources.busy||loading" :aria-label="'取消本条消息的附件引用 '+file.name" title="仅取消本次引用，不删除会话文件" @click="resourceClient.remove(file.id)"><el-icon aria-hidden="true"><Close /></el-icon></button></div>
      </TransitionGroup>
      <p v-if="resources.files.length" class="composer-attachment-note">发送时引用这些会话文件，取消引用不会删除文件</p>
      <textarea
        ref="textareaRef"
        v-model="draft"
        class="composer-textarea"
        :placeholder="loading ? '助手正在思考…' : '输入消息 或输入 / 选择技能命令'"
        :disabled="loading"
        rows="1"
        :aria-expanded="menuVisible" :aria-controls="menuVisible ? commandListId : undefined" :aria-activedescendant="menuVisible ? commandListId+'-'+activeCommand : undefined" aria-label="聊天消息或技能命令"
        @input="handleInput"
        @focus="refreshCommands"
        @blur="menuDismissed=true"
        @keydown="handleKey"
      />
      <div class="composer-toolbar">
        <input ref="fileInputRef" type="file" multiple hidden accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" @change="uploadFiles" />
        <button class="composer-add" type="button" aria-label="添加附件" :title="composerUploadHint(resources,loading)" :disabled="!resources.ready||!resources.filesEnabled||resources.busy||loading" @click="fileInputRef?.click()"><el-icon aria-hidden="true"><Plus /></el-icon></button>
        <span class="composer-permission" title="工具按当前账号权限执行，敏感操作仍需人工确认"><el-icon aria-hidden="true"><Lock /></el-icon><span>按账号权限</span></span>
        <span v-if="resources.busy" class="composer-upload-status" role="status">处理中</span>
        <select aria-label="使用模型" :title="composerModelTitle(resources,modelLocked,loading)" :value="resources.modelId" :disabled="!resources.ready||resources.busy||modelLocked||loading" @change="selectModel"><option value="">{{ composerDefaultModel(resources) }}</option><option v-if="selectedModelMissing(resources)" :value="resources.modelId" disabled>原选模型已不可用，请重新选择</option><option v-for="model in resources.models" :key="model.id" :value="model.id">{{ modelLabel(model) }}</option></select>
        <span class="composer-context" title="使用本会话历史与已授权的资料"><el-icon aria-hidden="true"><Document /></el-icon><span>会话上下文</span></span>
      </div>

      <button
        class="composer-voice"
        :class="{ recording, transcribing: voiceOpening || voiceStopping || voiceTranscribing }"
        :disabled="!active || voiceOpening || voiceStopping || voiceTranscribing || !!pendingVoice || (!recording && loading)"
        type="button"
        :aria-label="voiceButtonLabel"
        :aria-pressed="recording"
        :title="voiceButtonLabel"
        @click="toggleVoiceRecording"
      >
        <svg v-if="!voiceOpening && !voiceStopping && !voiceTranscribing" aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <path d="M12 19v3"/>
        </svg>
        <span v-else class="voice-spinner" aria-hidden="true"></span>
      </button>
      <button v-if="run?.local&&run.runId&&!draft.trim()&&!resources.files.length" type="button" class="composer-stop" aria-label="停止任务" title="停止当前任务" @click="emit('stop')"><svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg></button>
      <button v-else
        type="button"
        class="composer-send"
        :class="{ active: draft.trim() && !loading }"
        :disabled="loading || resources.busy || (!draft.trim()&&!resources.files.length)"
        @click="handleSend"
        title="发送" aria-label="发送消息"
      >
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 19V5M5 12l7-7 7 7"/>
        </svg>
      </button>
    </div>
    <Transition name="slash-menu"><section v-if="pendingVoice" class="composer-voice-review" aria-label="待插入的语音识别结果"><h4><AppIcon name="ChatDotRound" :size="16" />识别结果待插入</h4><p>原输入已保留，追加后仍需手动发送。未插入结果会在关闭面板或切换会话时清除。</p><details class="composer-voice-text"><summary>查看识别全文<AppIcon class="composer-voice-chevron" name="ArrowDown" :size="13" /></summary><div class="composer-voice-result" tabindex="0" role="region" aria-label="已识别的语音全文，可使用方向键滚动">{{ pendingVoice.text }}</div></details><div class="composer-voice-actions"><button type="button" :disabled="loading || resources.busy" @click="insertPendingVoice"><AppIcon name="Plus" :size="14" />追加到输入</button><button type="button" @click="pendingVoice=null;voiceHint='已放弃此段识别结果，原输入保留'"><AppIcon name="Close" :size="14" />放弃此段</button></div></section></Transition>
    <p v-if="resources.error" class="command-error" role="alert">{{ resources.error }}</p>
    <div class="model-selection-feedback"><span v-if="modelLocked" role="status">任务结束后可切换模型</span><span v-else-if="selectedModelMissing(resources)" role="status">原选模型已不在可用目录，请选择其他模型</span><span v-else-if="resources.modelNotice" role="status">{{ resources.modelNotice }}</span><span v-if="resources.ready&&resources.fallbackEnabled">请求失败时可使用备用模型，实际调用见执行轨迹</span><button v-if="resources.modelError" type="button" :disabled="resources.busy||loading" @click="resourceClient.refreshModels()">核对模型选择</button></div>
    <p v-if="resources.draftWarning" class="command-error" role="status">{{ resources.draftWarning }}</p>
    <p v-if="resources.storageWarning" class="composer-state-note" data-tone="warning" role="status"><AppIcon name="Warning" :size="14" />{{ resources.storageWarning }}</p>
    <p v-if="browserOffline" class="composer-state-note" data-tone="warning" role="status"><AppIcon name="Connection" :size="14" />浏览器报告网络离线，当前输入保留；恢复连接后请手动发送，不会自动重发。</p>
    <p v-if="resources.ready&&!resources.filesEnabled" class="composer-state-note">当前服务未启用会话文件上传</p>
    <p class="composer-hint" :role="voiceHint && !recording ? 'status' : undefined">{{ voiceHint || 'Enter 发送 · Shift + Enter 换行' }}</p>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount, getCurrentInstance } from 'vue'
import { ElMessage } from 'element-plus'
import { transcribeChatVoice } from '@/api/chatAssistant'
import request from '@/api/request'
import { useUserStore } from '@/stores/user'
import { filterSkillCommands } from '@/utils/skillCommands'
import {Plus,Document,Close,Lock} from '@element-plus/icons-vue'
import {ComposerResources,modelLabel,selectedModelMissing} from '@/utils/composerResources'
import {composerAttachment,composerDefaultModel,composerUploadHint,composerModelTitle} from '@/utils/composerPresentation'
import '@/assets/composer-presentation.css'

const props = defineProps({
  loading: { type: Boolean, default: false },sessionId:String,modelLocked:Boolean,run:Object,
  showPresets: { type: Boolean, default: true },active:{type:Boolean,default:true}
})

const emit = defineEmits(['send','stop'])
const draft = ref('')
let draftRevision=0
const commandListId='chat-skill-commands-'+getCurrentInstance().uid
const commandMenuRef=ref(null)
const browserOffline = ref(navigator.onLine === false)
const updateBrowserConnection = () => { browserOffline.value = navigator.onLine === false }
window.addEventListener('online',updateBrowserConnection)
window.addEventListener('offline',updateBrowserConnection)
const resources=ref({ready:false,files:[],models:[],modelId:'',busy:false,error:''}),fileInputRef=ref(null)
const resourceClient=new ComposerResources({base:(import.meta.env.VITE_API_URL||'').replace(/\/$/,''),onState:value=>{resources.value=value},onDraft:value=>{draft.value=value}})
watch(draft,value=>{draftRevision++;resourceClient.draft(value)},{flush:'sync'})
watch(()=>props.sessionId,id=>resourceClient.open(id),{immediate:true})
async function uploadFiles(event){const files=Array.from(event.target.files||[]);event.target.value='';try{await resourceClient.upload(files)}catch(error){resourceClient.publish({error:error.message})}}
async function selectModel(event){try{await resourceClient.select(event.target.value)}catch{/* Keep the server-confirmed selection. */}finally{event.target.value=resources.value.modelId}}
function sendPreset(text){if(props.loading||resources.value.busy)return;emit('send',resourceClient.content(text));resourceClient.clear()}
defineExpose({restoreDraft:value=>{if(!draft.value)draft.value=value},appendReference:value=>{if(/^@file:[a-f0-9-]{36}$/.test(value)){draft.value=(draft.value?draft.value.trimEnd()+' ':'')+value+' ';nextTick(()=>{textareaRef.value?.focus();autoResize()})}}})
const user=useUserStore(), commandCatalog=ref(null), commandError=ref(''), menuDismissed=ref(false), activeCommand=ref(0)
const commandOptions=computed(()=>filterSkillCommands(commandCatalog.value,draft.value))
const menuVisible=computed(()=>!props.loading&&!menuDismissed.value&&commandOptions.value.length>0)
let commandGeneration=0
async function refreshCommands(){const generation=++commandGeneration;commandCatalog.value=null;commandError.value='';try{const response=await request.get('/api/agent/commands');if(generation===commandGeneration)commandCatalog.value=response.data}catch{if(generation===commandGeneration){commandCatalog.value=null;commandError.value='技能目录暂不可用 可用 /help 查看命令帮助'}}}
function handleInput(){menuDismissed.value=false;activeCommand.value=0}
function selectCommand(item){draft.value=item.value.trimEnd()+' ';menuDismissed.value=true;activeCommand.value=0;nextTick(()=>{textareaRef.value?.focus();autoResize()})}
function handleKey(event){if(event.isComposing||event.keyCode===229)return;if(menuVisible.value&&!event.shiftKey){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();menuDismissed.value=true;return}
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();activeCommand.value=(activeCommand.value+(event.key==='ArrowDown'?1:-1)+commandOptions.value.length)%commandOptions.value.length;return}
  if(event.key==='Tab'||event.key==='Enter'){event.preventDefault();selectCommand(commandOptions.value[activeCommand.value]||commandOptions.value[0]);return}
}if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();handleSend()}}
watch(()=>[user.username,user.role],()=>{commandGeneration++;commandCatalog.value=null;draft.value='';menuDismissed.value=true;commandError.value=''})
watch(commandOptions,options=>{if(activeCommand.value>=options.length)activeCommand.value=0})
watch(()=>[menuVisible.value,activeCommand.value,commandOptions.value[activeCommand.value]?.value],async()=>{
  await nextTick()
  const menu=commandMenuRef.value,option=menu?.querySelector('[aria-selected="true"]')
  if(!menuVisible.value||!menu||!option)return
  const bounds=menu.getBoundingClientRect(),selected=option.getBoundingClientRect()
  if(selected.top<bounds.top+8)menu.scrollTop-=bounds.top+8-selected.top
  else if(selected.bottom>bounds.bottom-8)menu.scrollTop+=selected.bottom-bounds.bottom+8
},{flush:'post'})
const recording = ref(false)
const voiceTranscribing = ref(false)
const voiceOpening=ref(false),voiceStopping=ref(false),pendingVoice=ref(null)
const voiceHint = ref('')
const recordingSeconds = ref(0)
let mediaRecorder = null
let mediaStream = null
let recordingTimer = null
let voiceGeneration=0,composerDisposed=false
const voiceScope=()=>JSON.stringify([props.sessionId,user.identity?.userId || user.username,user.role,user.isAuthenticated,props.active])
const currentVoice=operation=>!composerDisposed && props.active && operation.generation===voiceGeneration && operation.scope===voiceScope()
const voiceButtonLabel=computed(()=>voiceOpening.value?'正在等待麦克风授权':voiceStopping.value?'正在结束录音':voiceTranscribing.value?'正在识别语音':pendingVoice.value?'请先处理待插入的语音结果':recording.value?'停止录音并识别':'语音输入')
const MAX_RECORDING_SECONDS = 60

const voiceMimeOptions = [
  { mimeType: 'audio/webm;codecs=opus', extension: 'webm' },
  { mimeType: 'audio/webm', extension: 'webm' },
  { mimeType: 'audio/mp4', extension: 'mp4' },
  { mimeType: 'audio/ogg;codecs=opus', extension: 'ogg' }
]

const quickChips = [
  { label: '业务地图', text: '显示系统业务地图和功能入口', icon: 'Collection' },
  { label: '缺陷统计', text: '查询最近检测任务的缺陷数量', icon: 'DataAnalysis' },
  { label: '质检记录', text: '查询我有权限查看的质检记录', icon: 'DocumentChecked' },
  { label: '批次追溯', text: '批次追溯在哪个页面操作', icon: 'DocumentCopy' },
  { label: '模型列表', text: '查询我有权限查看的模型列表', icon: 'Tickets' },
  { label: '工作统计', text: '查询本周工作统计', icon: 'DataAnalysis' },
  { label: '执行轨迹', text: '如何查看 AgentScope 调用轨迹', icon: 'Connection' },
  { label: '助手能力', text: '当前助手支持哪些只读查询', icon: 'ChatDotRound' }
]
const textareaRef = ref(null)

const autoResize = () => {
  nextTick(() => {
    const el = textareaRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 140) + 'px'
  })
}
watch(draft,autoResize,{flush:'post'})

const handleSend = () => {
  const value = resourceClient.content(draft.value)
  if (!value || props.loading||resources.value.busy) return
  emit('send', value)
  resourceClient.clear()
  draft.value = ''
  nextTick(() => {
    const el = textareaRef.value
    if (el) el.style.height = 'auto'
  })
}

const toggleVoiceRecording = async () => {
  if (recording.value) { stopVoiceRecording(); return }
  await startVoiceRecording()
}

const startVoiceRecording = async () => {
  if(!props.active || props.loading || voiceOpening.value || voiceStopping.value || voiceTranscribing.value || pendingVoice.value)return
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    ElMessage.warning('当前浏览器不支持语音输入')
    return
  }
  const operation={generation:++voiceGeneration,scope:voiceScope(),draftRevision}
  let stream,recorder
  voiceOpening.value=true
  voiceHint.value='正在等待麦克风授权'
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:true})
    if(!currentVoice(operation)){stream.getTracks().forEach(track=>track.stop());return}
    if(props.loading){stream.getTracks().forEach(track=>track.stop());voiceHint.value='当前消息正在处理，未开始录音，原输入保留';return}
    const mimeOption=chooseSupportedMimeType(),chunks=[]
    recorder=mimeOption.mimeType ? new MediaRecorder(stream,{mimeType:mimeOption.mimeType}) : new MediaRecorder(stream)
    const mimeType=recorder.mimeType || mimeOption.mimeType || 'audio/webm'
    const extension=voiceMimeOptions.find(option=>option.mimeType.split(';')[0]===mimeType.split(';')[0])?.extension || mimeOption.extension
    mediaStream=stream;mediaRecorder=recorder
    recorder.ondataavailable=event=>{if(currentVoice(operation) && mediaRecorder===recorder && event.data?.size>0)chunks.push(event.data)}
    recorder.onstop=()=>{
      if(!currentVoice(operation) || mediaRecorder!==recorder)return
      clearRecordingTimer();recording.value=false;voiceStopping.value=false;stopMediaTracks();mediaRecorder=null
      handleVoiceRecorded({...operation,chunks:[...chunks],mimeType,extension})
    }
    recorder.onerror=()=>{
      if(!currentVoice(operation))return
      clearVoiceState()
      voiceHint.value='录音中断，原输入保留，请重新录音'
      ElMessage.warning('录音中断，未重新提交识别')
    }
    recorder.start()
    recording.value=true;recordingSeconds.value=0
    voiceHint.value=`正在录音 0/${MAX_RECORDING_SECONDS} 秒，点击麦克风结束并识别`
    startRecordingTimer(operation)
  } catch {
    if(recorder){recorder.ondataavailable=null;recorder.onstop=null;recorder.onerror=null;try{if(recorder.state!=='inactive')recorder.stop()}catch{/* Already stopped. */}}
    stream?.getTracks().forEach(track=>track.stop())
    if(currentVoice(operation)){
      mediaRecorder=null;mediaStream=null;recording.value=false;clearRecordingTimer()
      voiceHint.value='无法打开麦克风，原输入保留，请检查浏览器权限'
      ElMessage.error('无法访问麦克风，请检查浏览器权限')
    }
  } finally {if(currentVoice(operation))voiceOpening.value=false}
}

const startRecordingTimer = operation => {
  clearRecordingTimer()
  recordingTimer=window.setInterval(()=>{
    if(!currentVoice(operation)){clearRecordingTimer();return}
    recordingSeconds.value++
    voiceHint.value=`正在录音 ${recordingSeconds.value}/${MAX_RECORDING_SECONDS} 秒，点击麦克风结束并识别`
    if(recordingSeconds.value>=MAX_RECORDING_SECONDS){ElMessage.info('已达到录音时长提示，正在结束并识别');stopVoiceRecording()}
  },1000)
}
const clearRecordingTimer = () => {if(recordingTimer){window.clearInterval(recordingTimer);recordingTimer=null}}
const chooseSupportedMimeType = () => {
  if(typeof MediaRecorder==='undefined' || typeof MediaRecorder.isTypeSupported!=='function')return {mimeType:'',extension:'webm'}
  return voiceMimeOptions.find(option=>MediaRecorder.isTypeSupported(option.mimeType)) || {mimeType:'',extension:'webm'}
}
const stopVoiceRecording = () => {
  clearRecordingTimer()
  if(mediaRecorder && mediaRecorder.state!=='inactive'){
    voiceStopping.value=true
    voiceHint.value='正在结束录音，请稍候'
    try{mediaRecorder.stop()}catch{clearVoiceState();voiceHint.value='录音结束状态未能核对，原输入保留，请重新录音';return}
  }
  recording.value=false
  stopMediaTracks()
}
const stopMediaTracks = () => {if(mediaStream){mediaStream.getTracks().forEach(track=>track.stop());mediaStream=null}}
function clearVoiceState(){
  voiceGeneration++
  clearRecordingTimer()
  const recorder=mediaRecorder;mediaRecorder=null
  if(recorder){recorder.ondataavailable=null;recorder.onstop=null;recorder.onerror=null;try{if(recorder.state!=='inactive')recorder.stop()}catch{/* Already stopped. */}}
  stopMediaTracks()
  recording.value=false;voiceOpening.value=false;voiceStopping.value=false;voiceTranscribing.value=false
  pendingVoice.value=null;voiceHint.value='';recordingSeconds.value=0
}
function appendVoiceText(text){draft.value+=(draft.value && !draft.value.endsWith('\n') ? '\n' : '')+text;autoResize()}
async function insertPendingVoice(){
  const result=pendingVoice.value
  if(!result || !currentVoice(result) || props.loading || resources.value.busy)return
  appendVoiceText(result.text);pendingVoice.value=null;voiceHint.value='语音已追加到输入框，请确认后发送'
  await nextTick()
  if(currentVoice(result))textareaRef.value?.focus({preventScroll:true})
}
async function handleVoiceRecorded(operation){
  if(!currentVoice(operation))return
  if(!operation.chunks.length){voiceHint.value='未记录到有效录音，原输入保留';return}
  voiceTranscribing.value=true;voiceHint.value='正在识别语音，原输入保留'
  try {
    const audioBlob=new Blob(operation.chunks,{type:operation.mimeType})
    const response=await transcribeChatVoice(audioBlob,`voice.${operation.extension}`)
    if(!currentVoice(operation))return
    const text=response.data?.data?.text
    if(typeof text!=='string' || !text.trim()){voiceHint.value='未识别到语音，原输入保留，请重新录音';return}
    if(draftRevision===operation.draftRevision && !props.loading && !resources.value.busy){
      appendVoiceText(text);voiceHint.value='语音已追加到输入框，请确认后发送'
    } else {
      pendingVoice.value={text,generation:operation.generation,scope:operation.scope}
      voiceHint.value='识别完成，原输入已保留，请核对待插入结果'
    }
  } catch(error) {
    if(currentVoice(operation)){
      ElMessage.error(error.response?.data?.message || error.message || '语音识别失败')
      voiceHint.value='语音识别失败，原输入保留；不会自动重新提交'
    }
  } finally {if(currentVoice(operation))voiceTranscribing.value=false}
}
watch(voiceScope,clearVoiceState,{flush:'sync'})
onBeforeUnmount(()=>{
  composerDisposed=true
  window.removeEventListener('online',updateBrowserConnection)
  window.removeEventListener('offline',updateBrowserConnection)
  resourceClient.close();commandGeneration++;clearVoiceState()
})
</script>

<style scoped>
.composer {
  position: relative;
  padding: 12px 20px 16px;
  background: #ffffff;
  flex-shrink: 0;
}
.composer-voice-review{margin:10px 0;padding:12px 14px;border-left:3px solid var(--app-primary);border-radius:0 8px 8px 0;background:var(--app-primary-light);color:var(--app-text);min-width:0}
.composer-voice-review h4{display:flex;align-items:center;gap:7px;margin:0;font-size:13px;font-weight:600;line-height:1.8}
.composer-voice-review h4>.el-icon{flex:0 0 auto;color:var(--app-primary)}
.composer-voice-review>p{margin:6px 0 10px;font-size:12px;line-height:1.85;color:var(--app-text-secondary);overflow-wrap:anywhere}
.composer-voice-result{max-height:140px;overflow:auto;overscroll-behavior:contain;font-size:13px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere;padding:4px 2px;scrollbar-gutter:stable}
.composer-voice-text>summary{display:flex;align-items:center;gap:6px;width:fit-content;color:var(--app-primary);font-size:12px;line-height:1.85;cursor:pointer;transition:color 180ms ease}
.composer-voice-text>summary:hover{color:var(--app-primary-hover)}
.composer-voice-chevron{transition:transform 180ms ease}.composer-voice-text[open]>summary .composer-voice-chevron{transform:rotate(180deg)}
.composer-voice-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-top:12px}
.composer-voice-actions button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:34px;padding:6px 10px;border:1px solid var(--app-border);border-radius:6px;background:var(--app-surface);color:var(--app-text-secondary);font:inherit;font-size:12px;cursor:pointer;transition:background-color 180ms ease,border-color 180ms ease,transform 180ms ease}
.composer-voice-actions button:first-child{color:white;border-color:var(--app-primary);background:var(--app-primary)}
.composer-voice-actions button:hover:not(:disabled){border-color:var(--app-primary)}
.composer-voice-actions button:first-child:hover:not(:disabled){background:var(--app-primary-hover)}
.composer-voice-actions button:active:not(:disabled){transform:scale(.98)}
.composer-voice-actions button:disabled{opacity:.6;cursor:default}
.composer-voice-actions button:focus-visible,.composer-voice-text>summary:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px;border-radius:3px}
.composer-voice-result:focus-visible{outline:2px solid var(--app-primary);outline-offset:-2px;border-radius:3px}
@media(max-height:600px){.composer-voice-result{max-height:80px}}
@media(prefers-reduced-motion:reduce){.composer-voice-actions button,.composer-voice-text>summary,.composer-voice-chevron{transition:none}.composer-voice-actions button{transform:none!important}.composer .voice-spinner{animation:none}}
.slash-menu{position:absolute;left:20px;right:20px;bottom:100%;z-index:20;max-height:320px;overflow:auto;background:white;border:1px solid #dce7f6;border-radius:14px;box-shadow:0 10px 28px #163c7020;padding:8px}.slash-menu p{font-size:11px;color:#64748b;padding:0 8px}.slash-menu button{display:flex;flex-direction:column;gap:4px;width:100%;text-align:left;background:white;color:#24354c;border:0;border-radius:8px;padding:10px;cursor:pointer;transition:background .15s,transform .15s}.slash-menu button span{font-size:12px;color:#64748b;overflow-wrap:anywhere}.slash-menu button.active,.slash-menu button:hover{background:#eef5ff}.slash-menu button:active{transform:scale(.99)}.slash-menu-enter-active,.slash-menu-leave-active{transition:opacity .15s,transform .15s}.slash-menu-enter-from,.slash-menu-leave-to{opacity:0;transform:translateY(5px)}.command-error{font-size:12px;color:#64748b}@media(prefers-reduced-motion:reduce){.slash-menu-enter-active,.slash-menu-leave-active,.slash-menu button{transition:none;transform:none!important}}

/* ── 快捷指令 ── */
.quick-chips {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 8px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.quick-chips::-webkit-scrollbar { display: none; }

.quick-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 32px;
  padding: 6px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #fff;
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.quick-chip:hover {
  border-color: #2563eb;
  color: #2563eb;
  background: #f8faff;
}

.quick-chip :deep(svg) {
  flex-shrink: 0;
}

.composer-input-wrap {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 8px;
  padding: 8px 10px 8px 16px;
  border: 1px solid #dfe5ee;
  border-radius: 20px;
  background: #ffffff;
  box-shadow: 0 4px 18px rgba(25, 49, 85, .045);
  min-height: 70px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.composer-input-wrap:focus-within {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(79, 110, 247, 0.08);
  background: #fff;
}

.composer-textarea {
  flex: 1 0 100%;width:100%;min-width:0;
  border: none;
  outline: none;
  resize: none;
  font: inherit;
  font-size: 14px;
  line-height: 1.55;
  max-height: 140px;
  background: transparent;
  color: #1e293b;
  padding: 4px 0;
}
.composer-toolbar{display:flex;align-items:center;gap:8px;flex:1;min-width:0}.composer-toolbar select{max-width:210px;min-width:0;border:0;background:transparent;color:#475569;padding:7px;border-radius:8px;font:inherit;font-size:12px}.composer-add{display:grid;place-items:center;width:34px;height:34px;border:0;border-radius:9px;background:transparent;color:#475569;font-size:21px;cursor:pointer;transition:background .15s,transform .15s}.composer-add:hover:not(:disabled){background:#eff6ff;transform:scale(1.04)}.composer-add:disabled{opacity:.4;cursor:default}.composer-attachments{width:100%;display:flex;gap:6px;flex-wrap:wrap}.composer-attachment{display:flex;align-items:center;gap:5px;border:1px solid #dbe5f1;border-radius:10px;padding:5px 7px;max-width:220px;font-size:12px}.composer-attachment>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.composer-attachment button{border:0;background:none;cursor:pointer;color:#64748b}.composer-upload-status{font-size:11px;color:#64748b}@media(max-width:480px){.composer-toolbar select{max-width:170px}}@media(prefers-reduced-motion:reduce){.composer-add{transition:none;transform:none!important}}

.composer-textarea::placeholder {
  color: #94a3b8;
}

.composer-textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.composer-send {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: #e2e8f0;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s;
}

.composer-voice {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: #eef2ff;
  color: #2563eb;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s;
}

.composer-voice:hover:not(:disabled) {
  background: #e0e7ff;
  transform: scale(1.05);
}

.composer-voice.recording {
  background: #fee2e2;
  color: #dc2626;
  box-shadow: 0 0 0 6px rgba(220, 38, 38, 0.08);
}

.composer-voice:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.voice-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(79, 110, 247, 0.25);
  border-top-color: #2563eb;
  border-radius: 999px;
  animation: voice-spin 0.8s linear infinite;
}

@keyframes voice-spin {
  to { transform: rotate(360deg); }
}

.composer-send.active {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  box-shadow: 0 2px 8px rgba(47, 107, 255, 0.25);
}

.composer-send.active:hover {
  transform: scale(1.06);
  box-shadow: 0 4px 14px rgba(47, 107, 255, 0.32);
}

.composer-send:disabled {
  cursor: not-allowed;
}

.composer-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--app-text-secondary);
  text-align: center;
}
.composer-send:active:not(:disabled), .quick-chip:active { transform: scale(.96); }
.quick-chip:focus-visible, .composer-send:focus-visible, .composer-voice:focus-visible { outline: 2px solid #2563eb; outline-offset: 3px; }
@media (max-width: 540px) { .composer { padding: 10px 12px 12px; } .quick-chips { gap: 5px; } .composer-input-wrap { padding-left: 12px; gap: 4px; } }
</style>
<style scoped>
.composer{padding-top:8px}.composer :deep(.conversation-controls){margin:0 2px -7px;padding:6px 10px 12px;background:#f2f3f5;border-radius:18px 18px 6px 6px}.composer :deep(.conversation-queue){background:transparent;margin:0;max-height:150px}.gpt-composer-input{position:relative;z-index:1;border-radius:26px;padding:14px 14px 10px;gap:5px;background:#fff;border-color:#d9dde3;box-shadow:0 2px 10px #18223706;min-height:124px}.gpt-composer-input .composer-textarea{min-height:58px;padding:2px 2px 10px;font-size:14px}.composer-toolbar{gap:9px}.composer-toolbar select{margin-left:auto;font-size:12px;max-width:200px;text-overflow:ellipsis}.composer-permission,.composer-context{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;font-size:12px;color:#64748b}.composer-context{border-left:1px solid #e2e5e9;padding-left:10px}.composer-context .el-icon{font-size:15px}.composer-voice{background:transparent;color:#697586}.composer-stop{display:grid;place-items:center;width:36px;height:36px;flex-shrink:0;border:0;border-radius:50%;background:#e4e7eb;color:#313842;cursor:pointer;transition:transform .15s}.composer-stop:hover{transform:scale(1.04)}.gpt-composer-input .composer-send.active{background:#202a37;color:#fff}.composer-permission .el-icon{font-size:15px}.composer-add{color:#424b58}.gpt-composer-input .composer-send,.gpt-composer-input .composer-voice{width:34px;height:34px}@media(max-width:600px){.composer-permission>span,.composer-context{display:none}.composer-toolbar select{max-width:160px;flex:1}.composer-toolbar{gap:3px}.gpt-composer-input{padding:12px 10px 9px}}@media(prefers-reduced-motion:reduce){.composer-stop{transition:none;transform:none!important}}

</style>
