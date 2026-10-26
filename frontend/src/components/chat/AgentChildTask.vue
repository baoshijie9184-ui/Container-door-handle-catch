<template>
 <section class="wb-child-task" aria-label="专业任务结果与追加要求">
  <p class="wb-child-state"><AppIcon name="Connection" :size="16" /><span>{{ view.explanation }}</span></p>
  <button v-if="view.nextView && availableViews.includes(view.nextView)" type="button" :disabled="busy" @click="$emit('view',view.nextView)"><AppIcon :name="view.nextView==='QUESTION'?'ChatDotRound':'DocumentChecked'" :size="14" />{{ view.nextLabel }}</button>
  <section class="wb-child-result" aria-label="最近保存的专业结果"><h4><AppIcon name="Document" :size="16" />最近保存的结果</h4><template v-if="view.output"><p class="wb-child-result-note">{{ view.resultNote }}</p><p class="wb-child-excerpt-label">结果摘录，完整内容可展开查看</p><p class="wb-child-excerpt">{{ view.excerpt }}</p><details><summary>展开已保存结果</summary><pre tabindex="0" aria-label="已保存的专业结果，纯文本展示">{{ view.output }}</pre></details></template><p v-else class="wb-note">本次读取没有返回可显示的专业结果，请结合执行轨迹核对，不补造分析结论。</p></section>
  <form v-if="view.canAppend" class="wb-child-followup" @submit.prevent="append"><label :for="inputId">补充专业要求<textarea :id="inputId" :value="text" rows="3" :maxlength="CHILD_FOLLOWUP_LIMIT" :disabled="busy" :aria-describedby="inputId+'-hint'" placeholder="填写本专业任务需要继续分析的范围或重点" @input="$emit('update:value',$event.target.value)" /></label><p :id="inputId+'-hint'" class="wb-note">{{ text.length }} / {{ CHILD_FOLLOWUP_LIMIT }} 字符。沿用原专业角色与工具权限；草稿仍在本页保留，提交结果请核对记录，不自动重发。</p><button type="submit" class="wb-button-primary" :disabled="busy || !ready"><AppIcon name="Plus" :size="14" />追加专业要求</button></form>
  <div v-if="view.canCancel && !recoveryShown" class="wb-child-cancel"><p>取消所选专业任务不会回滚已完成的业务操作；主任务和其他专业任务的状态分别核对。</p><button type="button" class="wb-button-danger" :disabled="busy" @click="$emit('cancel')"><AppIcon name="Close" :size="14" />取消此专业任务</button></div>
 </section>
</template>
<script setup>
import {computed,getCurrentInstance} from 'vue'
import {CHILD_FOLLOWUP_LIMIT,childTaskPresentation,childFollowupReady} from '@/utils/childTaskPresentation'
import '@/assets/agent-child-task.css'
const props=defineProps({item:{type:Object,required:true},value:{type:String,default:''},busy:Boolean,recoveryShown:Boolean,availableViews:{type:Array,default:()=>[]}})
const emit=defineEmits(['update:value','command','cancel','view'])
const inputId=`child-followup-${getCurrentInstance().uid}`
const text=computed(()=>typeof props.value==='string'?props.value:'')
const view=computed(()=>childTaskPresentation(props.item)),ready=computed(()=>childFollowupReady(text.value))
function append(){if(!props.busy && view.value.canAppend && ready.value)emit('command',text.value)}
</script>
