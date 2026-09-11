<template>
  <div class="composer">
    <!-- 快捷指令 chips -->
    <div class="quick-chips" v-if="!loading">
      <button
        v-for="chip in quickChips"
        :key="chip.text"
        class="quick-chip"
        @click="$emit('send', chip.text)"
      >
        <span v-html="chip.icon"></span>
        {{ chip.label }}
      </button>
    </div>
    <div class="composer-input-wrap">
      <textarea
        ref="textareaRef"
        v-model="draft"
        class="composer-textarea"
        :placeholder="loading ? '助手正在思考…' : '输入消息，例如：查看严重缺陷证据、批次追溯或模型灰度状态'"
        :disabled="loading"
        rows="1"
        @input="autoResize"
        @keydown.enter.exact.prevent="handleSend"
      />
      <button
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
        :disabled="loading || !draft.trim()"
        @click="handleSend"
        title="发送"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
      </button>
    </div>
    <p class="composer-hint">{{ voiceHint || 'Enter 发送 · Shift + Enter 换行' }}</p>
  </div>
</template>

<script setup>
import { ref, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { transcribeChatVoice } from '@/api/chatAssistant'

const props = defineProps({
  loading: { type: Boolean, default: false }
})

const emit = defineEmits(['send'])
const draft = ref('')
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
  { label: '缺陷证据', text: '查看严重缺陷证据', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10.3 3.5 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.5a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>' },
  { label: '质检队列', text: '查看待复核质检队列和返工复检任务', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>' },
  { label: '批次追溯', text: '查询批次 BATCH-001 的追溯报告', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h10"/><path d="M7 4v16"/></svg>' },
  { label: '模型灰度', text: '查看模型评估指标、灰度发布和回滚状态', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3v18"/><path d="M5 8h14"/><path d="M5 16h14"/></svg>' },
  { label: '质量报表', text: '生成本周质量处置统计和质检工作量报表', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>' },
  { label: 'Agent健康', text: '查看 Agent checkpoint 和健康状态', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 12h-4l-3 7-6-14-3 7H2"/><path d="M17 4h4v4"/></svg>' },
  { label: '运维链路', text: '检查OSS、Kafka和远程Worker运行状态', icon: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>' }
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
  const value = draft.value.trim()
  if (!value || props.loading) return
  emit('send', value)
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
  padding: 8px 20px 16px;
  background: #ffffff;
  border-top: 1px solid rgba(15, 23, 42, 0.06);
  flex-shrink: 0;
}

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
  border-color: #4f6ef7;
  color: #4f6ef7;
  background: #f8faff;
}

.quick-chip :deep(svg) {
  flex-shrink: 0;
}

.composer-input-wrap {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 8px 10px 8px 16px;
  border: 1.5px solid #e2e8f0;
  border-radius: 20px;
  background: #f8fafc;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.composer-input-wrap:focus-within {
  border-color: #4f6ef7;
  box-shadow: 0 0 0 3px rgba(79, 110, 247, 0.08);
  background: #fff;
}

.composer-textarea {
  flex: 1;
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
  color: #4f6ef7;
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
  border-top-color: #4f6ef7;
  border-radius: 999px;
  animation: voice-spin 0.8s linear infinite;
}

@keyframes voice-spin {
  to { transform: rotate(360deg); }
}

.composer-send.active {
  background: linear-gradient(135deg, #4f6ef7, #3b5de7);
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
  color: #cbd5e1;
  text-align: center;
}
</style>
