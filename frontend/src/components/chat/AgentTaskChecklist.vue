<template>
 <section v-if="view.total" class="wb-checklist" :aria-labelledby="headingId">
  <header><h4 :id="headingId"><AppIcon name="Tickets" :size="16" />任务步骤</h4><span>本次已读 {{ view.total.toLocaleString('zh-CN') }} 项</span></header>
  <ul class="wb-checklist-counts" aria-label="本次清单各阶段数量"><li v-for="group in view.counts" :key="group.key" :data-phase="group.key">{{ group.label }} <strong>{{ group.count.toLocaleString('zh-CN') }}</strong></li></ul>
  <p class="wb-checklist-note">步骤状态以本次已读清单为准，不代替业务回执或人工审批。{{ view.withEvidence ? '已记录证据编号 '+view.withEvidence.toLocaleString('zh-CN')+' 项，可逐项展开核对。' : '本次清单尚未提供执行证据编号。' }}</p>
  <div class="wb-checklist-scroll" :class="{'is-long':view.total>6}" :role="view.total>6?'region':undefined" :tabindex="view.total>6?0:undefined" :aria-label="view.total>6?'任务步骤，长清单可在此区域滚动阅读':undefined">
   <ol class="wb-checklist-rows">
    <li v-for="step in view.rows" :key="step.key">
     <span class="wb-checklist-ordinal" aria-hidden="true">{{ step.ordinal }}</span>
     <div class="wb-checklist-step"><div class="wb-checklist-title"><strong>{{ step.title }}</strong><StatusBadge domain="task" :code="step.code" :label="step.group==='unknown'?'步骤状态待核对':undefined" /></div>
      <p v-if="step.group==='unknown'" class="wb-checklist-note">原状态：{{ step.rawCode || '未记录' }}</p>
      <details v-if="step.evidence" class="wb-checklist-evidence"><summary>执行证据编号</summary><p>{{ step.evidence }}</p><a v-if="step.href" :href="step.href" target="_blank" rel="noopener noreferrer">查看证据所属执行<AppIcon name="TopRight" :size="13" /></a><p v-else class="wb-checklist-note">未提供可打开的执行编号，可从本任务执行轨迹继续核对。</p></details>
     </div>
    </li>
   </ol>
  </div>
 </section>
</template>
<script setup>
import {computed,getCurrentInstance} from 'vue'
import AppIcon from '../AppIcon.vue'
import StatusBadge from '../StatusBadge.vue'
import {taskChecklistPresentation} from '@/utils/taskChecklistPresentation'
import '@/assets/agent-task-checklist.css'
const props=defineProps({tasks:Array})
const headingId='wb-checklist-'+getCurrentInstance().uid
const view=computed(()=>taskChecklistPresentation(props.tasks))
</script>
