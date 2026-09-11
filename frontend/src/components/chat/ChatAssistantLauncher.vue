<template>
  <button
    ref="launcherRef"
    class="launcher-btn"
    :class="{ 'is-dragging': isDragging }"
    :style="btnStyle"
    @mousedown="onMouseDown"
    @touchstart.passive="onTouchStart"
    @click="onClick"
    title="智能助手"
  >
    <span class="launcher-ring"></span>
    <span class="launcher-icon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z"/>
        <path d="M8 12h8a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0"/>
        <path d="M12 12v4"/>
        <circle cx="8" cy="8" r="1" fill="currentColor"/>
        <circle cx="16" cy="8" r="1" fill="currentColor"/>
        <rect x="8" y="16" width="8" height="4" rx="2"/>
      </svg>
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
  right: 28px;
  bottom: 28px;
  z-index: 1200;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 22px;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, #1e3a5f 0%, #2f6bff 50%, #5b9cff 100%);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  box-shadow:
    0 4px 16px rgba(47, 107, 255, 0.25),
    0 12px 40px rgba(16, 35, 63, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
  cursor: grab;
  transition: box-shadow 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  letter-spacing: 0.02em;
  user-select: none;
  touch-action: none;
}

.launcher-btn:hover {
  box-shadow:
    0 8px 28px rgba(47, 107, 255, 0.35),
    0 20px 56px rgba(16, 35, 63, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.16);
}

.launcher-btn.is-dragging {
  cursor: grabbing;
  transition: none;
}

.launcher-btn:active:not(.is-dragging) {
  transform: scale(0.98);
}

.launcher-ring {
  position: absolute;
  inset: -4px;
  border-radius: 999px;
  border: 2px solid rgba(47, 107, 255, 0.3);
  animation: launcher-pulse 2.4s ease-in-out infinite;
  pointer-events: none;
}

.launcher-btn.is-dragging .launcher-ring {
  animation: none;
  opacity: 0;
}

@keyframes launcher-pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 0;
  }
  50% {
    transform: scale(1.08);
    opacity: 1;
  }
  100% {
    transform: scale(1);
    opacity: 0;
  }
}

.launcher-icon {
  width: 36px;
  height: 36px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(6px);
  flex-shrink: 0;
}

.launcher-text {
  white-space: nowrap;
}

@media (max-width: 768px) {
  .launcher-btn {
    padding: 12px 16px;
    gap: 8px;
  }

  .launcher-icon {
    width: 32px;
    height: 32px;
  }

  .launcher-text {
    font-size: 13px;
  }
}
</style>
