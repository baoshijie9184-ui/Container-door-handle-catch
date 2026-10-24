<template>
  <div class="wb-interaction" :data-interaction="item.kind" :aria-busy="busy">
    <template v-if="item.kind === 'PLAN'">
      <details class="wb-plan-feedback">
        <summary><AppIcon name="Edit" :size="14" />填写修订意见</summary>
        <label class="wb-input-label">需要调整的范围或步骤
          <textarea :value="text" :disabled="busy" :maxlength="WORKBENCH_RESPONSE_LIMIT" rows="3" placeholder="填写后可要求修订，计划修改后需要重新审阅" @input="$emit('update:value', $event.target.value)" />
        </label>
        <p class="wb-input-hint">{{ text.length }} / {{ WORKBENCH_RESPONSE_LIMIT }} 字符</p>
      </details>
      <p class="wb-decision-scope"><AppIcon name="DocumentChecked" :size="15" />批准当前 V{{ item.revision ?? '未知' }} 执行范围，检测、分派等业务确认仍独立进行</p>
      <p v-if="text.trim()" class="wb-input-hint">修订意见尚未提交；批准计划仍按当前正文执行。</p>
      <div class="wb-actions">
        <button type="button" class="wb-button-primary" :disabled="busy" @click="command('approve-plan')"><AppIcon name="CircleCheck" :size="14" />批准计划</button>
        <button type="button" :disabled="busy || !text.trim() || text.length > WORKBENCH_RESPONSE_LIMIT" @click="command('revise-plan', { feedback: text })">要求修订</button>
        <button type="button" class="wb-button-quiet" :disabled="busy" @click="command('cancel')">取消计划</button>
      </div>
    </template>
    <form v-else-if="item.kind === 'QUESTION'" @submit.prevent="answer">
      <fieldset class="wb-question-fields" :disabled="busy">
        <legend>{{ type === 'TEXT' ? '填写回答' : type === 'SINGLE' ? '选择一项' : type === 'MULTIPLE' ? '选择一项或多项' : '问题格式待核对' }}</legend>
        <template v-if="type === 'TEXT'">
          <textarea :value="text" :maxlength="WORKBENCH_RESPONSE_LIMIT" rows="4" aria-label="问题回答" placeholder="补充完成任务所需的信息" @input="$emit('update:value', $event.target.value)" />
          <p class="wb-input-hint">{{ text.length }} / {{ WORKBENCH_RESPONSE_LIMIT }} 字符</p>
        </template>
        <div v-else-if="options.length" class="wb-answer-options">
          <label v-for="option in options" :key="option" class="wb-answer-option" :class="{ 'is-selected': selected(option) }">
            <input :type="type === 'SINGLE' ? 'radio' : 'checkbox'" :name="`workbench-question-${item.id}`" :checked="selected(option)" :value="option" @change="choose(option, $event.target.checked)" />
            <span>{{ option }}</span>
          </label>
        </div>
        <p v-else class="wb-note">问题类型或选项不完整，请刷新核对；不会猜测回答。</p>
      </fieldset>
      <p class="wb-input-hint">{{ type === 'MULTIPLE' ? `已选择 ${Array.isArray(value) ? value.length : 0} 项 · ` : '' }}提交后继续原任务，回答不授予业务操作权限</p>
      <div class="wb-actions"><button type="submit" class="wb-button-primary" :disabled="busy || !ready"><AppIcon name="ChatDotRound" :size="14" />提交回答</button><button type="button" class="wb-button-quiet" :disabled="busy" @click="command('cancel')">取消问题</button></div>
    </form>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { WORKBENCH_RESPONSE_LIMIT, workbenchQuestionType, workbenchQuestionOptions, workbenchAnswerReady } from '@/utils/workbenchPresentation'
const props = defineProps({ item: { type: Object, required: true }, value: { type: [String, Array], default: '' }, busy: Boolean })
const emit = defineEmits(['update:value', 'command'])
const text = computed(() => typeof props.value === 'string' ? props.value : '')
const type = computed(() => workbenchQuestionType(props.item.data))
const options = computed(() => type.value === 'UNKNOWN' ? [] : workbenchQuestionOptions(props.item.data))
const ready = computed(() => workbenchAnswerReady(props.item.data, props.value))
function selected(option) { return type.value === 'SINGLE' ? props.value === option : Array.isArray(props.value) && props.value.includes(option) }
function choose(option, checked) {
  if (props.busy) return
  if (type.value === 'SINGLE') emit('update:value', option)
  else { const current = Array.isArray(props.value) ? props.value : []; emit('update:value', checked ? [...current.filter(value => value !== option), option] : current.filter(value => value !== option)) }
}
function command(action, input) { if (!props.busy) emit('command', { action, input }) }
function answer() { if (ready.value) command('answer', { answer: props.value }) }
</script>
