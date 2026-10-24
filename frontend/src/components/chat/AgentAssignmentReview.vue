<template>
  <section class="assignment-review" aria-label="质检分派参数对照">
    <h4><AppIcon name="User" :size="16" />质检分派参数</h4>
    <p class="assignment-review-note">对照本提议保存的原登记与拟修改值，未重新读取任务当前状态。账号权限和任务版本仍在确认时重新核对。</p>
    <dl class="assignment-review-facts"><dt>检测任务</dt><dd>{{ action.command.taskId }}</dd></dl>
    <div class="assignment-review-columns" aria-hidden="true"><span>提议前登记</span><span>拟分派设置</span></div>
    <div v-for="row in rows" :key="row.key" class="assignment-review-row">
      <h5>{{ row.label }}</h5>
      <div class="assignment-review-pair">
        <div v-for="side in sides" :key="side.key" class="assignment-review-value" :data-side="side.key">
          <span class="assignment-review-side">{{ side.label }}</span>
          <p :class="{'assignment-review-excerpt':row[side.key].folded}">{{ row[side.key].preview }}</p>
          <details v-if="row[side.key].folded" class="assignment-review-full"><summary>{{ side.label }}完整内容</summary><pre tabindex="0" :aria-label="row.label+' · '+side.label+'完整内容'">{{ row[side.key].text }}</pre></details>
        </div>
      </div>
    </div>
    <details class="assignment-review-registration"><summary><AppIcon name="Document" :size="14" />账号快照与分派回执登记<AppIcon class="assignment-review-chevron" name="ArrowDown" :size="13" /></summary><dl class="assignment-review-facts"><dt>拟分派账号快照</dt><dd>{{ action.command.assigneeRevision || '历史提议未记录' }}</dd><template v-if="action.result?.after"><dt>分派操作人</dt><dd>{{ action.result.after.assignedByName || '未记录' }}</dd><dt>操作人 ID</dt><dd>{{ action.result.after.assignedByUserId ?? '未记录' }}</dd><dt>分派身份版本</dt><dd>{{ action.result.after.assignmentRevision ?? '未记录' }}</dd></template></dl><p class="assignment-review-note">这里仅展示已返回的登记资料；当前操作结果以上方状态及审计为准。</p></details>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { assignmentReviewRows } from '@/utils/assignmentReviewPresentation'
import '@/assets/assignment-review.css'
const props = defineProps({ action: { type: Object, required: true } })
const rows = computed(() => assignmentReviewRows(props.action.before, props.action.command))
const sides = [{ key: 'before', label: '提议前登记' }, { key: 'proposed', label: '拟分派设置' }]
</script>
