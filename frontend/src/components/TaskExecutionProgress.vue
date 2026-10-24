<template>
 <section class="task-execution-progress" aria-label="任务阶段进度与上传回执">
  <div class="task-execution-counts"><span>登记图片 <strong>{{ view.total }}</strong> 张</span><span>已记录上传回执 <strong>{{ view.uploaded }}</strong> 条</span></div>
  <el-progress v-if="view.percentage!==null" aria-label="界面阶段提示，不代表逐张推理进度" :percentage="view.percentage" :stroke-width="5" :status="view.status" :format="value=>value+'%'" />
  <p class="task-progress-basis">{{ view.percentage===null ? '阶段进度未记录。' : '此进度按界面阶段展示，不是模型逐张推理百分比。' }} 未收到上传回执不等于上传失败。</p>
  <p v-if="view.error" class="task-progress-error" role="alert"><AppIcon name="Warning" :size="15" /><span>已记录的异常：{{ view.error }}</span></p>
  <p v-else-if="view.code==='RESULT_RECORDED'" class="task-progress-message"><AppIcon name="Search" :size="14" /><span>本机只保存了结束阶段，未保存完整检测状态。请重新读取任务追溯核对结果。</span></p>
  <p v-else-if="view.message || view.code==='PARTIAL_FAILED'" class="task-progress-message"><AppIcon :name="view.code==='PARTIAL_FAILED'?'Warning':'Clock'" :size="14" /><span>{{ view.code==='PARTIAL_FAILED' ? '检测部分失败，请打开结果与追溯核对。' : view.message }}</span></p>
  <p class="task-progress-time"><AppIcon name="Clock" :size="14" />最近更新 {{ updatedAt }} · UTC+8</p>
 </section>
</template>
<script setup>
import {computed} from 'vue'
import {taskExecutionProgress} from '@/utils/taskExecutionPresentation'
import {beijingDateTime} from '@/utils/beijingTime'
const props=defineProps({task:{type:Object,required:true}})
const view=computed(()=>taskExecutionProgress(props.task))
const updatedAt=computed(()=>props.task.updatedAt ? beijingDateTime(props.task.updatedAt)||'时间格式未知' : '未记录')
</script>
<style scoped>
.task-execution-progress { min-width:0; margin-top:12px; }
.task-execution-counts { display:flex; flex-wrap:wrap; gap:8px 18px; margin-bottom:9px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.task-execution-counts strong { color:var(--app-text); font-weight:600; }
.task-progress-basis { margin:8px 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.task-progress-message,.task-progress-error,.task-progress-time { display:flex; align-items:flex-start; gap:6px; margin:8px 0; font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.task-progress-message,.task-progress-time { color:var(--app-text-secondary); }
.task-progress-error { color:var(--app-danger); }
.task-execution-progress p > .el-icon { flex-shrink:0; margin-top:3px; }
.task-progress-time { margin-bottom:0; }
</style>
