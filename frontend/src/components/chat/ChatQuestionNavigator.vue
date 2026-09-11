<template>
  <div v-if="questions.length" ref="rootRef" class="question-navigator">
    <button
      ref="triggerRef"
      type="button"
      class="question-nav-trigger"
      aria-label="查看历史提问"
      aria-controls="chat-question-list"
      :aria-expanded="String(open)"
      title="查看历史提问"
      @click="open = !open"
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <line x1="5" y1="6" x2="19" y2="6" />
        <line x1="5" y1="10" x2="17" y2="10" />
        <line x1="5" y1="14" x2="15" y2="14" />
        <line x1="5" y1="18" x2="12" y2="18" />
      </svg>
      <span class="question-nav-count">{{ questions.length }}</span>
    </button>

    <transition name="question-popover">
      <section v-if="open" id="chat-question-list" class="question-nav-popover" aria-label="当前会话历史提问">
        <header>
          <strong>历史提问</strong>
          <span>当前会话 · {{ questions.length }} 条</span>
        </header>
        <div class="question-nav-list">
          <button
            v-for="(question, index) in questions"
            :key="question.key"
            type="button"
            class="question-nav-item"
            :class="{ active: question.key === activeKey }"
            :title="question.content"
            @click="selectQuestion(question.key)"
          >
            <span class="question-nav-index">{{ index + 1 }}</span>
            <span class="question-nav-text">{{ question.content }}</span>
          </button>
        </div>
      </section>
    </transition>
  </div>
</template>

<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  questions: { type: Array, default: () => [] },
  activeKey: { type: String, default: '' },
  resetKey: { type: [String, Number], default: '' }
})

const emit = defineEmits(['locate'])
const rootRef = ref(null)
const triggerRef = ref(null)
const open = ref(false)

const close = (restoreFocus = false) => {
  open.value = false
  if (restoreFocus) nextTick(() => triggerRef.value?.focus())
}

const selectQuestion = (key) => {
  emit('locate', key)
  close()
}

const handlePointerDown = (event) => {
  if (open.value && rootRef.value && !rootRef.value.contains(event.target)) close()
}

const handleKeyDown = (event) => {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    event.stopPropagation()
    close(true)
  }
}

watch(() => props.resetKey, () => close())
watch(() => props.questions.length, (length) => {
  if (!length) close()
})

onMounted(() => {
  document.addEventListener('pointerdown', handlePointerDown)
  document.addEventListener('keydown', handleKeyDown, true)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', handlePointerDown)
  document.removeEventListener('keydown', handleKeyDown, true)
})
</script>

<style scoped>
.question-navigator { position: absolute; right: 10px; top: 50%; z-index: 18; transform: translateY(-50%); }
.question-nav-trigger { position: relative; width: 44px; height: 44px; border: 1px solid #dbe3ef; border-radius: 14px; background: rgba(255,255,255,.96); color: #52647a; display: grid; place-items: center; cursor: pointer; box-shadow: 0 8px 24px rgba(15,23,42,.14); transition: color .2s, border-color .2s, box-shadow .2s; }
.question-nav-trigger:hover, .question-nav-trigger[aria-expanded="true"] { color: #3b5de7; border-color: #aab9ff; box-shadow: 0 10px 28px rgba(59,93,231,.2); }
.question-nav-trigger:focus-visible, .question-nav-item:focus-visible { outline: 3px solid rgba(79,110,247,.3); outline-offset: 2px; }
.question-nav-count { position: absolute; top: -5px; right: -5px; min-width: 18px; height: 18px; padding: 0 4px; border: 2px solid white; border-radius: 999px; background: #4f6ef7; color: white; font-size: 10px; font-weight: 800; line-height: 14px; }
.question-nav-popover { position: absolute; right: 0; top: 50px; width: min(280px, calc(100vw - 32px)); max-height: min(420px, 60vh); overflow: hidden; border: 1px solid #dbe3ef; border-radius: 18px; background: rgba(255,255,255,.98); box-shadow: 0 18px 45px rgba(15,23,42,.18); }
.question-nav-popover header { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; padding: 13px 14px 10px; border-bottom: 1px solid #eef2f7; }
.question-nav-popover strong { color: #172033; font-size: 14px; }
.question-nav-popover header span { color: #94a3b8; font-size: 10.5px; white-space: nowrap; }
.question-nav-list { max-height: min(350px, 50vh); padding: 7px; overflow-y: auto; }
.question-nav-item { width: 100%; min-height: 44px; padding: 8px 10px; border: 0; border-radius: 11px; background: transparent; color: #334155; display: grid; grid-template-columns: 24px minmax(0,1fr); align-items: center; gap: 7px; text-align: left; cursor: pointer; }
.question-nav-item:hover { background: #f3f6fa; }
.question-nav-item.active { background: #eef2ff; color: #3549ba; font-weight: 650; }
.question-nav-index { width: 22px; height: 22px; border-radius: 7px; background: #f1f5f9; color: #64748b; display: grid; place-items: center; font-size: 10px; font-weight: 800; }
.question-nav-item.active .question-nav-index { background: #4f6ef7; color: white; }
.question-nav-text { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 13px; }
.question-popover-enter-active, .question-popover-leave-active { transition: opacity .18s ease, transform .18s ease; transform-origin: top right; }
.question-popover-enter-from, .question-popover-leave-to { opacity: 0; transform: translateY(-4px) scale(.98); }
@media (max-width: 480px) { .question-navigator { right: 8px; } .question-nav-popover { right: -2px; width: min(272px, calc(100vw - 24px)); } }
@media (prefers-reduced-motion: reduce) { .question-nav-trigger, .question-popover-enter-active, .question-popover-leave-active { transition: none; } }
</style>
