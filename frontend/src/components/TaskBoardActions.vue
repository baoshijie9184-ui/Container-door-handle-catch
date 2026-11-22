<template>
  <div class="row-actions">
    <template v-if="uploadsOnly">
      <router-link v-if="previewTaskId" :to="actionLink(previewTaskId, 'images')">查看原图</router-link>
      <el-button v-else link disabled>查看原图</el-button>
      <template v-if="supervisor">
        <el-button v-if="!dispatchReason" size="small" :type="awaitingDispatch ? 'primary' : 'default'" @click="emit('dispatch', { upload: row })">
          {{ applicationId ? '选用此批次' : '派发检测任务' }}
        </el-button>
        <router-link v-if="!awaitingDispatch && row.formalVerificationTaskId" :to="assignedTrace(row.formalVerificationTaskId)">查看已派任务</router-link>
        <router-link v-else-if="!awaitingDispatch && row.taskType !== 'SINGLE' && ['WAITING_CHECK','VERIFYING'].includes(row.listPhase)"
          class="next-action" :to="{ path: '/inspection/tasks/verification', query: { keyword: row.taskId } }">前往校验</router-link>
        <small v-if="dispatchReason" class="action-note">{{ dispatchReason }}</small>
      </template>
      <template v-else>
        <router-link v-if="row.myDetectionTaskId && ['READY','FAILED'].includes(row.myDetectionStatus)" class="next-action"
          :to="{ path: '/inspection/tasks', query: { assignedTaskId: row.myDetectionTaskId } }">去完成检测任务</router-link>
        <router-link v-else-if="row.myDetectionTaskId && row.myDetectionStatus !== 'CANCELLED'" :to="assignedTrace(row.myDetectionTaskId)">
          {{ ['COMPLETED','PARTIAL_FAILED'].includes(row.myDetectionStatus) ? '查看检测结果' : '查看检测进度' }}
        </router-link>
        <small v-else class="action-note">{{ row.myDetectionTaskId ? '检测任务已取消' : '未分派给我' }}</small>
      </template>
    </template>
    <template v-else>
      <el-button v-if="Number(row.mine) && row.flow !== 'RECHECK_REQUIRED' && ['READY','FAILED'].includes(row.modelStatus)" size="small" type="primary" :disabled="busy" @click="emit('start', row)">
        {{ row.modelStatus === 'FAILED' ? '重试模型检测' : '启动模型检测' }}
      </el-button>
      <el-button v-if="supervisor && row.taskType === 'OSS_FOLDER' && row.phase === 'READY'" size="small" @click="emit('assign', row)">改派检测</el-button>
      <template v-if="canReview(row)">
        <router-link v-if="supervisor && !row.qualityAssignee" class="next-action" :to="actionLink(row.taskId, 'assign')">分派校验任务</router-link>
        <router-link v-if="canOperateQuality" :class="{ 'next-action': !!row.qualityAssignee }"
          :to="actionLink(row.taskId, 'review')">核对模型结果</router-link>
        <router-link v-if="supervisor && row.qualityAssignee" :to="actionLink(row.taskId, 'assign')">改派校验</router-link>
      </template>
      <template v-if="row.listPhase === 'FOLLOW_UP'">
        <template v-if="canOperateQuality">
          <router-link v-if="row.flow === 'REWORK_REQUIRED'" class="next-action" :to="actionLink(row.taskId, 'rework')">登记返工结果</router-link>
          <template v-else-if="row.flow === 'RECHECK_REQUIRED'">
            <el-button type="primary" size="small" :disabled="busy || !!row.recheckBlockedReason" @click="emit('recheck', row)">启动复检</el-button>
            <small v-if="row.recheckBlockedReason" class="action-note">{{ row.recheckBlockedReason }}</small>
          </template>
          <router-link v-else-if="row.flow === 'HOLD' || row.flow === 'CONFIRMED'" class="next-action"
            :to="actionLink(row.taskId, 'disposition')">{{ row.flow === 'HOLD' ? '处理暂挂' : '安排复检' }}</router-link>
        </template>
        <router-link v-if="supervisor" :to="actionLink(row.taskId, 'assign')">{{ row.qualityAssignee ? '改派校验' : '分派校验任务' }}</router-link>
      </template>
      <button v-if="taskList === 'detection' && !['SINGLE','OSS_FOLDER'].includes(row.taskType) && row.modelStatus !== 'UPLOADING' && ossFolder"
        type="button" @click="emit('dispatch', { upload: row })">派发检测任务</button>
      <button v-else-if="supervisor && !taskList && row.taskType !== 'SINGLE' && ossFolder" type="button"
        @click="emit('dispatch', { prefix: row.prefix })">以此目录派单</button>
      <router-link :to="actionLink(row.taskId, 'trace')">任务详情</router-link>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { assignedTrace } from '@/utils/taskBoardNavigation'
import { canReview } from '@/utils/taskBoardStages'

const props = defineProps({
  row: { type: Object, required: true },
  actionLink: { type: Function, required: true },
  username: String,
  taskList: String,
  previewTaskId: String,
  dispatchReason: String,
  applicationId: String,
  supervisor: Boolean,
  uploadsOnly: Boolean,
  awaitingDispatch: Boolean,
  busy: Boolean
})
const emit = defineEmits(['start', 'assign', 'dispatch', 'recheck'])
const ossFolder = computed(() => props.row.prefix?.startsWith('detection/') && props.row.prefix.endsWith('/'))
const canOperateQuality = computed(() => props.supervisor || (props.row.qualityMine == null
  ? Boolean(props.username && props.row.qualityAssignee === props.username) : Boolean(Number(props.row.qualityMine))))
</script>

<style scoped>
.row-actions { display:flex; align-items:center; flex-wrap:wrap; gap:4px 12px; }
.row-actions :is(a,button) { white-space:normal; }
.row-actions a,.row-actions > button:not(.el-button) {
  display:inline-flex; align-items:center; min-height:32px; padding:0; color:var(--app-primary);
  background:none; border:0; font:inherit; font-size:13px; text-decoration:none; cursor:pointer;
}
.row-actions a:hover,.row-actions > button:not(.el-button):hover { text-decoration:underline; }
.row-actions a.next-action {
  padding:0 10px; border:1px solid transparent; border-radius:7px;
  background:var(--app-primary-soft); font-weight:650;
}
.row-actions a.next-action:hover { border-color:var(--app-primary); text-decoration:none; }
.row-actions :is(a,button):focus-visible { outline:2px solid var(--app-primary); outline-offset:2px; }
.row-actions :deep(.el-button) { min-height:32px; margin:0; }
.action-note { flex-basis:100%; color:var(--app-text-secondary); font-size:12px; }
@media (pointer:coarse), (max-width:600px) {
  .row-actions a,.row-actions > button:not(.el-button),.row-actions :deep(.el-button) { min-height:44px; }
}
</style>
