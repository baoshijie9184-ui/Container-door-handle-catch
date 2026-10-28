<template>
  <button
    ref="launcherRef"
    type="button"
    class="launcher-btn"
    :class="{ 'is-dragging': isDragging }"
    :style="btnStyle"
    @mousedown="onMouseDown"
    @touchstart.passive="onTouchStart"
    @click="onClick"
    title="打开智能助手"
    aria-label="打开智能助手"
  >
    <span class="launcher-icon" aria-hidden="true">
      <AppIcon name="ChatDotRound" :size="20" />
    </span>
    <span class="launcher-text">智能助手</span>
  </button>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'

const emit = defineEmits(['open'])

const STORAGE_KEY = 'chatLauncherPos'
const SAFE_INSET = 12
const launcherRef = ref(null)

// 读取保存的位置，默认右下角
const loadPos = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const pos = JSON.parse(raw)
      if (typeof pos.x === 'number' && typeof pos.y === 'number') return pos
    }
  } catch {}
  return null
}

const savedPos = loadPos()
const posX = ref(savedPos?.x ?? null)
const posY = ref(savedPos?.y ?? null)

const btnStyle = computed(() => {
  if (posX.value !== null && posY.value !== null) {
    return { left: posX.value + 'px', top: posY.value + 'px', right: 'auto', bottom: 'auto' }
  }
  return {}
})

// 拖拽状态
const isDragging = ref(false)
let startX = 0, startY = 0, startPosX = 0, startPosY = 0
let hasMoved = false

const getBtnRect = () => {
  const el = launcherRef.value
  return el ? el.getBoundingClientRect() : { left: 0, top: 0, width: 140, height: 50 }
}

const savePosition = () => {
  if (posX.value === null || posY.value === null) return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ x: posX.value, y: posY.value }))
  } catch { /* ignore storage restrictions */ }
}

const clampToViewport = () => {
  if (posX.value === null || posY.value === null) return
  const rect = getBtnRect()
  const maxX = Math.max(SAFE_INSET, window.innerWidth - rect.width - SAFE_INSET)
  const maxY = Math.max(SAFE_INSET, window.innerHeight - rect.height - SAFE_INSET)
  posX.value = Math.min(Math.max(posX.value, SAFE_INSET), maxX)
  posY.value = Math.min(Math.max(posY.value, SAFE_INSET), maxY)
  savePosition()
}

const onMouseDown = (e) => {
  e.preventDefault()
  startDrag(e.clientX, e.clientY)
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

const onTouchStart = (e) => {
  const touch = e.touches[0]
  startDrag(touch.clientX, touch.clientY)
  document.addEventListener('touchmove', onTouchMove, { passive: false })
  document.addEventListener('touchend', onTouchEnd)
}

const startDrag = (clientX, clientY) => {
  isDragging.value = true
  hasMoved = false
  startX = clientX
  startY = clientY
  const rect = getBtnRect()
  startPosX = rect.left
  startPosY = rect.top
}

const onMouseMove = (e) => {
  moveDrag(e.clientX, e.clientY)
}

const onTouchMove = (e) => {
  e.preventDefault()
  const touch = e.touches[0]
  moveDrag(touch.clientX, touch.clientY)
}

const moveDrag = (clientX, clientY) => {
  const dx = clientX - startX
  const dy = clientY - startY
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasMoved = true

  let newX = startPosX + dx
  let newY = startPosY + dy

  // 限制在视口内
  const rect = getBtnRect()
  const maxX = Math.max(SAFE_INSET, window.innerWidth - rect.width - SAFE_INSET)
  const maxY = Math.max(SAFE_INSET, window.innerHeight - rect.height - SAFE_INSET)
  newX = Math.max(SAFE_INSET, Math.min(newX, maxX))
  newY = Math.max(SAFE_INSET, Math.min(newY, maxY))

  posX.value = newX
  posY.value = newY
}

const onMouseUp = () => {
  endDrag()
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
}

const onTouchEnd = () => {
  endDrag()
  document.removeEventListener('touchmove', onTouchMove)
  document.removeEventListener('touchend', onTouchEnd)
}

const endDrag = () => {
  isDragging.value = false
  if (hasMoved && posX.value !== null) {
    clampToViewport()
  }
}

const onClick = () => {
  if (!hasMoved) {
    emit('open')
  }
}

onMounted(() => {
  window.addEventListener('resize', clampToViewport)
  nextTick(clampToViewport)
})

onUnmounted(() => {
  window.removeEventListener('resize', clampToViewport)
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
  document.removeEventListener('touchmove', onTouchMove)
  document.removeEventListener('touchend', onTouchEnd)
})
</script>

<style scoped>
.launcher-btn {
  position: fixed;
  right: 24px;
  bottom: 20px;
  z-index: 1200;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height:44px;
  padding:7px 13px 7px 8px;
  border:1px solid var(--app-border);
  border-radius:10px;
  background:var(--app-surface);
  color:var(--app-text);
  font-size:12px;
  font-weight:550;
  box-shadow:var(--app-shadow-sm);
  cursor: grab;
  transition: background-color 180ms ease,box-shadow 180ms ease,transform 180ms ease;
  letter-spacing: 0.02em;
  user-select: none;
  touch-action: none;
}

.launcher-btn:hover {
  background:var(--app-surface);
  border-color:var(--app-border-focus);
  box-shadow:var(--app-shadow-md);
}

.launcher-btn.is-dragging {
  cursor: grabbing;
  transition: none;
}

.launcher-btn:active:not(.is-dragging) {
  transform: scale(0.98);
}

.launcher-icon {
  width:28px;
  height:28px;
  border-radius:7px;
  display: flex;
  align-items: center;
  justify-content: center;
  background:var(--app-primary-soft);
  color:var(--app-primary);
  flex-shrink: 0;
}

.launcher-text {
  white-space: nowrap;
}

@media (max-width: 768px) {
  .launcher-btn {
    width:44px;
    height:44px;
    right:16px;
    bottom:calc(16px + env(safe-area-inset-bottom,0px));
    justify-content:center;
    padding:0;
    gap:0;
  }

  .launcher-icon {
    width: 32px;
    height: 32px;
  }

  .launcher-text {
    display:none;
  }
}
@media(prefers-reduced-motion:reduce) { .launcher-btn { transition:none; }.launcher-btn:active:not(.is-dragging) { transform:none; } }
</style>
