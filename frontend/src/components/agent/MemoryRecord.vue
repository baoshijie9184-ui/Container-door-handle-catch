<template>
  <article class="memory-item memory-record" :aria-label="'已保存记忆 '+(item.id || '编号未记录')">
    <div class="memory-record-status"><StatusBadge domain="memoryLifecycle" :code="memoryLifecycleCode(item.lifecycle,clock)" /><span>{{ expiryText }}</span></div>
    <template v-if="longText"><p class="memory-record-excerpt"><span>正文摘录</span>{{ excerpt }}<template v-if="excerpt.length<content.length">…</template></p><details class="memory-record-body"><summary>阅读完整正文</summary><pre tabindex="0" aria-label="此条记忆的完整正文">{{ content }}</pre></details></template>
    <p v-else class="memory-content">{{ content || '本次未返回记忆正文' }}</p>
    <details class="memory-record-source"><summary><AppIcon name="Document" :size="15" />来源与保存资料</summary>
      <dl><dt>记忆编号</dt><dd>{{ item.id || '未记录' }}</dd><dt>来源会话</dt><dd>{{ item.sourceSessionId || '未记录来源会话' }}</dd><dt>创建时间 · UTC+8</dt><dd>{{ memoryTime(item.createdAt) }}</dd><dt>更新时间 · UTC+8</dt><dd>{{ memoryTime(item.updatedAt) }}</dd><dt>治理版本</dt><dd>{{ revision ?? '未记录' }}</dd><dt>正文校验摘要</dt><dd>{{ item.digest || '未记录' }}</dd><dt>到期自动删除</dt><dd>{{ item.lifecycle?.autoDelete === true ? '已登记启用' : item.lifecycle?.autoDelete === false ? '未启用' : '设置未读取' }}</dd></dl>
      <router-link v-if="sourceSession && !disabled" :to="{path:'/agent/chat',query:{sessionId:sourceSession}}" class="memory-source-session"><AppIcon name="ChatDotRound" :size="15" />打开本人来源会话</router-link>
      <p v-else-if="sourceSession" class="memory-source-note">当前有操作或资料读取，请结束后打开来源会话。</p>
      <p class="memory-source-note">这里只展示已返回的保存资料。来源会话需重新核对当前账号权限；记忆摘要不证明原会话仍存在。</p>
    </details>
    <footer><span>{{ item.updatedAt ? '更新 '+memoryTime(item.updatedAt)+' · UTC+8' : item.createdAt ? '创建 '+memoryTime(item.createdAt)+' · UTC+8' : '保存时间未记录' }}</span>
      <div class="memory-actions"><el-button :disabled="disabled" @click="$emit('similar',item)"><AppIcon name="Search" :size="15" />查找相似</el-button><el-button :disabled="disabled" @click="$emit('policy',item)"><AppIcon name="Clock" :size="15" />有效期与停用</el-button><el-button :disabled="disabled" @click="$emit('edit',item)"><AppIcon name="Edit" :size="15" />编辑记忆</el-button><el-button type="danger" plain :disabled="disabled" @click="$emit('remove',item)"><AppIcon name="Delete" :size="15" />删除记忆</el-button></div>
    </footer>
  </article>
</template>
<script setup>
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { memoryLifecycleCode, memoryTime } from '@/utils/memoryPresentation'
import { knownCount } from '@/utils/countPresentation'
const props=defineProps({item:{type:Object,required:true},clock:Number,disabled:Boolean})
defineEmits(['similar','policy','edit','remove'])
const content=computed(()=>typeof props.item.memory==='string'?props.item.memory:'')
const longText=computed(()=>content.value.length>600||content.value.split(/\r?\n/).length>8)
const excerpt=computed(()=>Array.from(content.value.split(/\r?\n/).slice(0,4).join('\n')).slice(0,260).join(''))
const revision=computed(()=>knownCount(props.item.lifecycle?.revision))
const sourceSession=computed(()=>typeof props.item.sourceSessionId==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(props.item.sourceSessionId)?props.item.sourceSessionId:'')
const expiryText=computed(()=>!props.item.lifecycle?'有效期设置未读取':props.item.lifecycle.expiresAt?'有效期 '+memoryTime(props.item.lifecycle.expiresAt)+' · UTC+8':'未设置到期时间')
</script>
<style scoped>
.memory-record{min-width:0;overflow-wrap:anywhere}
.memory-record-status{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;margin-bottom:10px}
.memory-record-status>span:last-child{font-size:12px;color:var(--app-text-secondary);line-height:1.85}
.memory-record .memory-content,.memory-record-excerpt{white-space:pre-wrap;font-size:14px;color:var(--app-text);line-height:1.9;margin:10px 0;overflow-wrap:anywhere}
.memory-record-excerpt>span{display:block;font-size:12px;line-height:1.85;color:var(--app-text-secondary);margin-bottom:5px}
.memory-record summary{width:fit-content;max-width:100%;cursor:pointer;font-size:12px;color:var(--app-text-secondary);line-height:1.85;border-radius:3px;transition:color 180ms ease}
.memory-record summary:hover{color:var(--app-primary)}
.memory-record-body pre{margin:10px 0 0;max-height:300px;overflow:auto;overscroll-behavior:contain;white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.9 var(--app-font);color:var(--app-text);padding:10px 12px;border-left:2px solid var(--app-border)}
.memory-record-source{margin:12px 0}
.memory-record-source>summary>.el-icon{vertical-align:middle;margin-right:5px;color:var(--app-primary)}
.memory-record-source dl{display:grid;grid-template-columns:130px minmax(0,1fr);gap:7px 14px;margin:12px 0;font-size:12px;line-height:1.85}
.memory-record-source dt{color:var(--app-text-secondary)}
.memory-record-source dd{margin:0;min-width:0;overflow-wrap:anywhere;color:var(--app-text)}
.memory-source-session{display:inline-flex;align-items:center;gap:6px;padding:5px 0;color:var(--app-primary);font-size:12px;line-height:1.85;text-decoration:none}
.memory-source-session:hover{text-decoration:underline;text-underline-offset:3px}
.memory-record .memory-source-note{font-size:12px;line-height:1.85;color:var(--app-text-secondary);margin:8px 0}
.memory-record footer{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px 16px;margin-top:16px}
.memory-record footer>span{font-size:12px;line-height:1.85;color:var(--app-text-secondary)}
.memory-record .memory-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.memory-record .memory-actions>.el-button+.el-button{margin-left:0}
.memory-record :is(summary,pre,a):focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}
@media(max-width:540px){.memory-record-source dl{grid-template-columns:1fr;gap:3px}.memory-record-source dd{margin-bottom:7px}.memory-record .memory-actions{width:100%}}
@media(prefers-reduced-motion:reduce){.memory-record summary{transition:none}}
</style>
