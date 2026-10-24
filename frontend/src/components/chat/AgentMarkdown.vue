<template>
  <div class="agent-markdown">
    <template v-for="block in blocks" :key="block.id">
      <section v-if="block.type === 'code'" class="agent-code">
        <header><span>{{ block.language || '代码' }}</span><button type="button" :aria-label="isCopied(block) ? '代码已复制' : '复制代码'" @click="copyCode(block)"><AppIcon :name="isCopied(block) ? 'CircleCheck' : 'DocumentCopy'" :size="14" />{{ isCopied(block) ? '已复制' : '复制代码' }}</button></header>
        <pre tabindex="0" :aria-label="(block.language || '') + '代码，可选中复制'"><code>{{ block.text }}</code></pre>
        <p v-if="copyError?.id === block.id" class="agent-code-error" role="status">{{ copyError.text }}</p>
      </section>
      <div v-else-if="block.type === 'table'" class="agent-markdown-table" role="region" aria-label="消息表格，可横向滚动" tabindex="0">
        <table><thead><tr><th v-for="(cell, column) in block.headers" :key="column" scope="col" :style="{ textAlign: block.alignments[column] }"><InlineText :text="cell" /></th></tr></thead><tbody><tr v-for="(row, rowIndex) in block.rows" :key="rowIndex"><td v-for="(cell, column) in row" :key="column" :style="{ textAlign: block.alignments[column] }"><InlineText :text="cell" /></td></tr></tbody></table>
      </div>
      <component :is="'h' + Math.min(block.level + 1, 6)" v-else-if="block.type === 'heading'"><InlineText :text="block.text" /></component>
      <hr v-else-if="block.type === 'rule'" />
      <blockquote v-else-if="block.type === 'quote'"><InlineText :text="block.text" /></blockquote>
      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.type === 'list'" :start="block.start"><li v-for="(item, index) in block.items" :key="index"><InlineText :text="item" /></li></component>
      <p v-else><InlineText :text="block.text" /></p>
    </template>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, ref } from 'vue'
import AppIcon from '../AppIcon.vue'
import { messageBlocks, messageInline } from '../../utils/messageMarkdown'
import { skillInstallNavigation } from '../../utils/skillInstallNavigation'
import '../../assets/agent-markdown.css'

const props = defineProps({ text: { type: String, default: '' } })
const blocks = computed(() => {
  const install = skillInstallNavigation(props.text, window.location.href)
  return messageBlocks(install ? install.before + '[' + install.label + '](' + install.route + ')' + install.after : props.text)
})
const copied = ref(null), copyError = ref(null)
const isCopied = block => copied.value?.id === block.id && copied.value.text === block.text
let copyTimer, copyGeneration = 0
async function copyCode(block) {
  const generation = ++copyGeneration
  copyError.value = null
  copied.value = null
  window.clearTimeout(copyTimer)
  try {
    if (!navigator.clipboard?.writeText) throw new Error()
    await navigator.clipboard.writeText(block.text)
    if (generation !== copyGeneration) return
    copied.value = { id: block.id, text: block.text }
    copyTimer = window.setTimeout(() => { copied.value = null }, 1800)
  } catch {
    if (generation === copyGeneration) copyError.value = { id: block.id, text: '浏览器未允许复制，请选中代码后手动复制。' }
  }
}
onBeforeUnmount(() => { copyGeneration++; window.clearTimeout(copyTimer) })

function inlineNodes(tokens) {
  return tokens.map((token, key) => {
    if (token.type === 'text') return token.text
    if (token.type === 'code') return h('code', { key }, token.text)
    if (token.type === 'link') return h('a', { key, href: token.href, ...(token.external ? { target: '_blank', rel: 'noopener noreferrer', title: '在新标签页打开外部链接' } : {}) }, inlineNodes(token.children))
    return h(token.type === 'strong' ? 'strong' : 'em', { key }, inlineNodes(token.children))
  })
}
const InlineText = defineComponent({
  props: { text: { type: String, default: '' } },
  setup: inlineProps => () => h('span', { class: 'agent-inline' }, inlineNodes(messageInline(inlineProps.text)))
})
</script>
