<template>
  <div v-if="questions.length" ref="rootRef" class="question-navigator" :class="{ 'question-nav-inline': inline }">
    <button
      ref="triggerRef"
      type="button"
      class="question-nav-trigger"
      aria-label="查看历史提问"
      :aria-controls="open ? questionListId : undefined"
      :aria-expanded="String(open)"
      title="查看历史提问"
      @click="open = !open"
      @keydown.down.prevent="open=true"
      @keydown.up.prevent="open=true"
    >
      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <line x1="5" y1="6" x2="19" y2="6" />
        <line x1="5" y1="10" x2="17" y2="10" />
        <line x1="5" y1="14" x2="15" y2="14" />
        <line x1="5" y1="18" x2="12" y2="18" />
      </svg>
      <span class="question-nav-count">{{ questions.length }}</span>
    </button>

    <Teleport to="body" :disabled="!inline"><transition name="question-popover">
      <section v-if="open" ref="popoverRef" :id="questionListId" class="question-nav-popover" :class="{ 'question-nav-floating': inline }" aria-label="当前会话历史提问" @keydown="handleListKey">
        <header>
          <strong>历史提问</strong>
          <span>当前会话 · {{ questions.length }} 条</span>
        </header>
        <p class="question-nav-help">方向键选择 · Enter 定位 · Escape 关闭</p>
        <div class="question-nav-list">
          <button
            v-for="(question, index) in questions"
            :key="question.key"
            type="button"
            class="question-nav-item"
            :class="{ active: question.key === activeKey }"
            :aria-current="question.key === activeKey ? 'location' : undefined"
            :title="question.content"
            @click="selectQuestion(question.key)"
          >
            <span class="question-nav-index">{{ index + 1 }}</span>
            <span class="question-nav-text">{{ question.content }}</span>
          </button>
        </div>
      </section>
    </transition></Teleport>
  </div>
</template>

<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch, getCurrentInstance } from 'vue'

const props = defineProps({
  inline: { type: Boolean, default: false },
  questions: { type: Array, default: () => [] },
  activeKey: { type: String, default: '' },
  resetKey: { type: [String, Number], default: '' }
})

const emit = defineEmits(['locate'])
const rootRef = ref(null)
const popoverRef = ref(null)
const triggerRef = ref(null)
const open = ref(false)
const questionListId='chat-question-list-'+getCurrentInstance().uid
function focusQuestion(button){
  if(!button)return
  button.focus({preventScroll:true})
  const list=popoverRef.value?.querySelector('.question-nav-list')
  if(!list)return
  const bounds=list.getBoundingClientRect(),item=button.getBoundingClientRect()
  if(item.top<bounds.top)list.scrollTop-=bounds.top-item.top
  else if(item.bottom>bounds.bottom)list.scrollTop+=item.bottom-bounds.bottom
}
function handleListKey(event){
  if(event.isComposing||event.altKey||event.ctrlKey||event.metaKey||!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return
  const buttons=[...popoverRef.value.querySelectorAll('.question-nav-item')]
  if(!buttons.length)return
  const current=buttons.indexOf(document.activeElement)
  const index=event.key==='Home'?0:event.key==='End'?buttons.length-1:(current+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length
  event.preventDefault();event.stopPropagation();focusQuestion(buttons[index])
}
watch(open,async visible=>{
  if(!visible)return
  await nextTick()
  if(open.value)focusQuestion(popoverRef.value?.querySelector('.question-nav-item.active')||popoverRef.value?.querySelector('.question-nav-item'))
})

const close = (restoreFocus = false) => {
  open.value = false
  if (restoreFocus) nextTick(() => triggerRef.value?.focus())
}

const selectQuestion = (key) => {
  emit('locate', key)
  close()
}

const handlePointerDown = (event) => {
  if (open.value && rootRef.value && !rootRef.value.contains(event.target) && !popoverRef.value?.contains(event.target)) close()
}
const handleFocusIn = event => {
  if(open.value&&!rootRef.value?.contains(event.target)&&!popoverRef.value?.contains(event.target))close()
}

const handleKeyDown = (event) => {
  if (event.key === 'Escape' && !event.isComposing && open.value && (rootRef.value?.contains(event.target)||popoverRef.value?.contains(event.target))) {
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
  document.addEventListener('focusin',handleFocusIn)
  document.addEventListener('keydown', handleKeyDown, true)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', handlePointerDown)
  document.removeEventListener('focusin',handleFocusIn)
  document.removeEventListener('keydown', handleKeyDown, true)
})
</script>

<style scoped>
.question-navigator { position:absolute; right:10px; top:50%; z-index:18; transform:translateY(-50%); }
.question-navigator.question-nav-inline { position:relative; top:auto; right:auto; transform:none; display:inline-flex; }
.question-nav-trigger { position:relative; display:grid; place-items:center; width:40px; height:40px; border:1px solid var(--app-border); border-radius:10px; background:var(--app-surface); color:var(--app-text-secondary); cursor:pointer; box-shadow:var(--app-shadow-sm); transition:color 180ms ease,border-color 180ms ease,background-color 180ms ease; }
.question-nav-trigger:hover,.question-nav-trigger[aria-expanded=true] { color:var(--app-primary); border-color:var(--app-border-focus); background:var(--app-primary-soft); }
.question-nav-trigger:focus-visible,.question-nav-item:focus-visible { outline:2px solid var(--app-primary); outline-offset:2px; }
.question-nav-count { position:absolute; top:-5px; right:-5px; min-width:17px; height:17px; padding:0 4px; border:2px solid white; border-radius:999px; background:var(--app-primary); color:white; font-size:10px; font-weight:600; line-height:13px; }
.question-nav-inline .question-nav-trigger { width:30px; height:28px; border-radius:6px; box-shadow:none; }
.question-nav-inline .question-nav-count { font-size:9px; min-width:14px; height:14px; line-height:10px; }
.question-nav-popover { position:absolute; right:0; top:50px; display:flex; flex-direction:column; width:min(300px,calc(100vw - 32px)); max-height:60vh; max-height:60dvh; overflow:hidden; border:1px solid var(--app-border); border-radius:12px; background:var(--app-surface); box-shadow:var(--app-shadow-lg); }
.question-nav-inline .question-nav-popover { top:auto; bottom:36px; right:0; }
.question-nav-popover.question-nav-floating { position:fixed; right:16px; top:min(140px,20vh); bottom:auto; z-index:3000; }
.question-nav-popover header { display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:6px 10px; flex-shrink:0; padding:14px 14px 8px; }
.question-nav-popover strong { color:var(--app-text); font-size:14px; font-weight:600; }
.question-nav-popover header span { color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.question-nav-help { flex-shrink:0; margin:0 0 5px; padding:0 14px 10px; border-bottom:1px solid var(--app-border); color:var(--app-text-secondary); font-size:11px; line-height:1.8; }
.question-nav-list { min-height:0; padding:7px; overflow-y:auto; overscroll-behavior:contain; }
.question-nav-item { display:grid; grid-template-columns:24px minmax(0,1fr); align-items:center; gap:8px; width:100%; min-height:42px; padding:9px 10px; border:0; border-radius:7px; background:transparent; color:var(--app-text-secondary); text-align:left; cursor:pointer; transition:background-color 160ms ease,color 160ms ease; }
.question-nav-item:hover { background:var(--app-bg); }
.question-nav-item.active { color:var(--app-primary); background:var(--app-primary-soft); font-weight:550; }
.question-nav-index { display:grid; place-items:center; width:22px; height:22px; border-radius:6px; background:var(--app-info-soft); color:var(--app-text-secondary); font-size:10px; font-weight:550; }
.question-nav-item.active .question-nav-index { background:var(--app-primary); color:white; }
.question-nav-text { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; white-space:normal; overflow-wrap:anywhere; font-size:12px; line-height:1.75; }
.question-popover-enter-active,.question-popover-leave-active { transition:opacity 180ms ease,transform 180ms ease; transform-origin:top right; }
.question-popover-enter-from,.question-popover-leave-to { opacity:0; transform:translateY(-4px); }
@media(max-width:480px) { .question-navigator { right:8px; } .question-nav-popover { right:-2px; } }
@media(prefers-reduced-motion:reduce) { .question-nav-trigger,.question-nav-item,.question-popover-enter-active,.question-popover-leave-active { transition:none; } .question-popover-enter-from,.question-popover-leave-to { transform:none; } }
</style>
