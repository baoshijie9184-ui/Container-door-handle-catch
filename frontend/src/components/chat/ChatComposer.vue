<template>
  <div class="composer">
    <Transition name="slash-menu">
      <section v-if="menuVisible" class="slash-menu" aria-label="技能命令建议">
        <p>选择命令后填写问题 Enter 或 Tab 补全 Escape 关闭</p>
        <div id="chat-skill-commands" role="listbox" aria-label="技能命令">
          <button v-for="(item,index) in commandOptions" :id="'chat-skill-command-'+index" :key="item.value" type="button" role="option" :aria-selected="index===activeCommand" :class="{active:index===activeCommand}" @mousedown.prevent @click="selectCommand(item)"><strong>{{ item.label }}</strong><span>{{ item.description }}</span></button>
        </div>
      </section>
    </Transition>
    <p v-if="commandError && draft.startsWith('/')" class="command-error" role="status">{{ commandError }}</p>
    <!-- 快捷指令 chips -->
    <div class="quick-chips" v-if="!loading">
      <button
        v-for="chip in quickChips"
        :key="chip.text"
        class="quick-chip"
        @click="sendPreset(chip.text)"
      >
        <span v-html="chip.icon"></span>
        {{ chip.label }}
      </button>
    </div>
    <slot name="queue" />
    <div class="composer-input-wrap gpt-composer-input">
      <TransitionGroup name="slash-menu" tag="div" class="composer-attachments" v-if="resources.files.length" aria-label="待发送附件">
        <div v-for="file in resources.files" :key="file.id" class="composer-attachment"><el-icon aria-hidden="true"><Document /></el-icon><span :title="file.name">{{ file.name }}</span><button type="button" :aria-label="'取消引用 '+file.name" @click="resourceClient.remove(file.id)"><el-icon><Close /></el-icon></button></div>
      </TransitionGroup>
      <textarea
        ref="textareaRef"
        v-model="draft"
        class="composer-textarea"
        :placeholder="loading ? '助手正在思考…' : '输入消息 或输入 / 选择技能命令'"
        :disabled="loading"
        rows="1"
        :aria-expanded="menuVisible" aria-controls="chat-skill-commands" :aria-activedescendant="menuVisible ? 'chat-skill-command-'+activeCommand : undefined" aria-label="聊天消息或技能命令"
        @input="handleInput"
        @focus="refreshCommands"
        @blur="menuDismissed=true"
        @keydown="handleKey"
      />
      <div class="composer-toolbar">
        <input ref="fileInputRef" type="file" multiple hidden accept=".png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.csv,.json,.html,.svg" @change="uploadFiles" />
        <button class="composer-add" type="button" aria-label="添加附件" title="上传会话私有文件" :disabled="!resources.ready||!resources.filesEnabled||resources.busy||loading" @click="fileInputRef?.click()"><el-icon><Plus /></el-icon></button>
        <span class="composer-permission" title="工具按当前账号权限执行，敏感操作仍需人工确认"><el-icon aria-hidden="true"><Lock /></el-icon><span>按账号权限</span></span>
        <span v-if="resources.busy" class="composer-upload-status" role="status">正在保存</span>
        <select aria-label="使用模型" :value="resources.modelId" :disabled="!resources.ready||resources.busy||modelLocked||loading" @change="selectModel"><option value="">系统默认</option><option v-for="model in resources.models" :key="model.id" :value="model.id">{{ model.model }}</option></select>
        <span class="composer-context" title="使用本会话历史与已授权的资料"><el-icon aria-hidden="true"><Document /></el-icon><span>会话上下文</span></span>
      </div>
      <button v-if="run?.local&&run.runId&&!draft.trim()&&!resources.files.length" type="button" class="composer-stop" aria-label="停止任务" title="停止当前任务" @click="emit('stop')"><svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg></button>
      <button v-else
        class="composer-voice"
        :class="{ recording, transcribing: voiceTranscribing }"
        :disabled="loading || voiceTranscribing"
        aria-label="语音输入"
        :title="recording ? '停止录音并识别' : '语音输入'"
        @click="toggleVoiceRecording"
      >
        <svg v-if="!voiceTranscribing" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <path d="M12 19v3"/>
        </svg>
        <span v-else class="voice-spinner"></span>
      </button>
      <button
        class="composer-send"
        :class="{ active: draft.trim() && !loading }"
        :disabled="loading || resources.busy || (!draft.trim()&&!resources.files.length)"
        @click="handleSend"
        title="发送" aria-label="发送消息"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
      </button>
    </div>
    <p v-if="resources.error" class="command-error" role="alert">{{ resources.error }}</p>
    <p class="composer-hint">{{ voiceHint || 'Enter 发送 · Shift + Enter 换行' }}</p>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { transcribeChatVoice } from '@/api/chatAssistant'
import request from '@/api/request'
import { useUserStore } from '@/stores/user'
import { filterSkillCommands } from '@/utils/skillCommands'
import {Plus,Document,Close,Lock} from '@element-plus/icons-vue'
import {ComposerResources} from '@/utils/composerResources'

const props = defineProps({
  loading: { type: Boolean, default: false },sessionId:String,modelLocked:Boolean,run:Object
})

const emit = defineEmits(['send','stop'])
const draft = ref('')
const resources=ref({ready:false,files:[],models:[],modelId:'',busy:false,error:''}),fileInputRef=ref(null)
const resourceClient=new ComposerResources({base:(import.meta.env.VITE_API_URL||'').replace(/\/$/,''),onState:value=>{resources.value=value}})
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
function handleInput(){menuDismissed.value=false;activeCommand.value=0;autoResize()}
function selectCommand(item){draft.value=item.value.trimEnd()+' ';menuDismissed.value=true;activeCommand.value=0;nextTick(()=>{textareaRef.value?.focus();autoResize()})}
function handleKey(event){if(event.isComposing||event.keyCode===229)return;if(menuVisible.value&&!event.shiftKey){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();menuDismissed.value=true;return}
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();activeCommand.value=(activeCommand.value+(event.key==='ArrowDown'?1:-1)+commandOptions.value.length)%commandOptions.value.length;return}
  if(event.key==='Tab'||event.key==='Enter'){event.preventDefault();selectCommand(commandOptions.value[activeCommand.value]||commandOptions.value[0]);return}
}if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();handleSend()}}
watch(()=>[user.username,user.role],()=>{commandGeneration++;commandCatalog.value=null;draft.value='';menuDismissed.value=true;commandError.value=''})
watch(commandOptions,options=>{if(activeCommand.value>=options.length)activeCommand.value=0})
const recording = ref(false)
const voiceTranscribing = ref(false)
const voiceHint = ref('')
const recordingSeconds = ref(0)
let mediaRecorder = null
let mediaStream = null
let audioChunks = []
let selectedVoiceMimeType = 'audio/webm'
let recordingTimer = null
const MAX_RECORDING_SECONDS = 60

const voiceMimeOptions = [
  { mimeType: 'audio/webm;codecs=opus', extension: 'webm' },
  { mimeType: 'audio/webm', extension: 'webm' },
  { mimeType: 'audio/mp4', extension: 'mp4' },
  { mimeType: 'audio/ogg;codecs=opus', extension: 'ogg' }
]

const quickChips = [
  { label: '业务地图', text: '显示系统业务地图和功能入口', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>' },
  { label: '缺陷统计', text: '查询最近检测任务的缺陷数量', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10.3 3.5 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.5a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>' },
  { label: '质检记录', text: '查询我有权限查看的质检记录', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>' },
  { label: '批次追溯', text: '批次追溯在哪个页面操作', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h10"/><path d="M7 4v16"/></svg>' },
  { label: '模型列表', text: '查询我有权限查看的模型列表', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3v18"/><path d="M5 8h14"/><path d="M5 16h14"/></svg>' },
  { label: '工作统计', text: '查询本周工作统计', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>' },
  { label: '执行轨迹', text: '如何查看 AgentScope 调用轨迹', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 12h-4l-3 7-6-14-3 7H2"/><path d="M17 4h4v4"/></svg>' },
  { label: '助手能力', text: '当前助手支持哪些只读查询', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>' }
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
  if (recording.value) {
    stopVoiceRecording()
    return
  }
  await startVoiceRecording()
}

const startVoiceRecording = async () => {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    ElMessage.warning('当前浏览器不支持语音输入')
    return
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    audioChunks = []
    const mimeOption = chooseSupportedMimeType()
    selectedVoiceMimeType = mimeOption.mimeType || 'audio/webm'
    mediaRecorder = mimeOption.mimeType
      ? new MediaRecorder(mediaStream, { mimeType: mimeOption.mimeType })
      : new MediaRecorder(mediaStream)
    mediaRecorder.ondataavailable = event => {
      if (event.data && event.data.size > 0) {
        audioChunks.push(event.data)
      }
    }
    mediaRecorder.onstop = handleVoiceRecorded
    mediaRecorder.start()
    recording.value = true
    recordingSeconds.value = 0
    voiceHint.value = `正在录音 0/${MAX_RECORDING_SECONDS} 秒，点击麦克风结束并识别`
    startRecordingTimer()
  } catch (error) {
    console.error('[chat] 麦克风打开失败:', error)
    ElMessage.error('无法访问麦克风，请检查浏览器权限')
  }
}

const startRecordingTimer = () => {
  clearRecordingTimer()
  recordingTimer = window.setInterval(() => {
    recordingSeconds.value += 1
    voiceHint.value = `正在录音 ${recordingSeconds.value}/${MAX_RECORDING_SECONDS} 秒，点击麦克风结束并识别`
    if (recordingSeconds.value >= MAX_RECORDING_SECONDS) {
      ElMessage.info('已达到最长录音时长，正在自动识别')
      stopVoiceRecording()
    }
  }, 1000)
}

const clearRecordingTimer = () => {
  if (recordingTimer) {
    window.clearInterval(recordingTimer)
    recordingTimer = null
  }
}

const chooseSupportedMimeType = () => {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return { mimeType: '', extension: 'webm' }
  }
  return voiceMimeOptions.find(option => MediaRecorder.isTypeSupported(option.mimeType)) || { mimeType: '', extension: 'webm' }
}

const voiceFileExtension = () => {
  const match = voiceMimeOptions.find(option => option.mimeType === selectedVoiceMimeType)
  return match?.extension || 'webm'
}

const stopVoiceRecording = () => {
  clearRecordingTimer()
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  }
  recording.value = false
  stopMediaTracks()
}

const stopMediaTracks = () => {
  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop())
    mediaStream = null
  }
}

const handleVoiceRecorded = async () => {
  if (!audioChunks.length) {
    voiceHint.value = ''
    return
  }
  voiceTranscribing.value = true
  voiceHint.value = '正在识别语音...'
  try {
    const audioBlob = new Blob(audioChunks, { type: selectedVoiceMimeType })
    const response = await transcribeChatVoice(audioBlob, `voice.${voiceFileExtension()}`)
    const text = response.data?.data?.text || ''
    if (!text.trim()) {
      ElMessage.warning('没有识别到有效语音内容')
      voiceHint.value = '未识别到语音，请靠近麦克风后重试'
      return
    }
    draft.value = text
    voiceHint.value = '已识别到输入框，请确认后发送'
    autoResize()
  } catch (error) {
    console.error('[chat] 语音识别失败:', error)
    ElMessage.error(error.response?.data?.message || error.message || '语音识别失败')
    voiceHint.value = '语音识别失败，请重试'
  } finally {
    voiceTranscribing.value = false
    audioChunks = []
  }
}

onBeforeUnmount(() => {
  resourceClient.close()
  commandGeneration++
  clearRecordingTimer()
  if (mediaRecorder) {
    mediaRecorder.ondataavailable = null
    mediaRecorder.onstop = null
    if (mediaRecorder.state !== 'inactive') mediaRecorder.stop()
  }
  mediaRecorder = null
  recording.value = false
  voiceTranscribing.value = false
  audioChunks = []
  voiceHint.value = ''
  stopMediaTracks()
})
</script>

<style scoped>
.composer {
  position: relative;
  padding: 12px 20px 16px;
  background: #ffffff;
  flex-shrink: 0;
}
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
  font-size: 11px;
  color: #68768a;
  text-align: center;
}
.composer-send:active:not(:disabled), .quick-chip:active { transform: scale(.96); }
.quick-chip:focus-visible, .composer-send:focus-visible, .composer-voice:focus-visible { outline: 2px solid #2563eb; outline-offset: 3px; }
@media (max-width: 540px) { .composer { padding: 10px 12px 12px; } .quick-chips { gap: 5px; } .composer-input-wrap { padding-left: 12px; gap: 4px; } }
</style>
<style scoped>
.composer{padding-top:8px}.composer :deep(.conversation-controls){margin:0 2px -7px;padding:6px 10px 12px;background:#f2f3f5;border-radius:18px 18px 6px 6px}.composer :deep(.conversation-queue){background:transparent;margin:0;max-height:150px}.gpt-composer-input{position:relative;z-index:1;border-radius:26px;padding:14px 14px 10px;gap:5px;background:#fff;border-color:#d9dde3;box-shadow:0 2px 10px #18223706;min-height:124px}.gpt-composer-input .composer-textarea{min-height:58px;padding:2px 2px 10px;font-size:14px}.composer-toolbar{gap:9px}.composer-toolbar select{margin-left:auto;font-size:12px;max-width:200px;text-overflow:ellipsis}.composer-permission,.composer-context{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;font-size:12px;color:#64748b}.composer-context{border-left:1px solid #e2e5e9;padding-left:10px}.composer-context .el-icon{font-size:15px}.composer-voice{background:transparent;color:#697586}.composer-stop{display:grid;place-items:center;width:36px;height:36px;flex-shrink:0;border:0;border-radius:50%;background:#e4e7eb;color:#313842;cursor:pointer;transition:transform .15s}.composer-stop:hover{transform:scale(1.04)}.gpt-composer-input .composer-send.active{background:#202a37;color:#fff}.composer-permission .el-icon{font-size:15px}.composer-add{color:#424b58}.gpt-composer-input .composer-send,.gpt-composer-input .composer-voice{width:34px;height:34px}@media(max-width:600px){.composer-permission>span,.composer-context{display:none}.composer-toolbar select{max-width:160px;flex:1}.composer-toolbar{gap:3px}.gpt-composer-input{padding:12px 10px 9px}}@media(prefers-reduced-motion:reduce){.composer-stop{transition:none;transform:none!important}}
</style>
