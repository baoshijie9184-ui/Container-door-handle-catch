<template>
  <article class="skill-version-record">
    <header><strong>版本 {{ version.version??'未记录' }}</strong><StatusBadge domain="skillVersion" :code="version.status" /><span v-if="active" class="skill-current-version">当前发布版本</span><span v-if="latest" class="skill-latest-version">最新可见版本</span></header>
    <p class="skill-version-description">{{ version.description||'适用场景未记录' }}</p>
    <details :open="latest" class="skill-version-body"><summary>查看版本正文</summary><pre tabindex="0" :aria-label="'版本 '+version.version+' 的技能正文'">{{ version.instructions||'正文未记录' }}</pre></details>
    <section class="skill-version-tools"><h4><AppIcon name="Key" :size="15" />工具范围</h4><p>{{ Array.isArray(version.tools)?version.tools.length?version.tools.join('、'):'正文参考，不新增工具':'工具清单未记录' }}</p></section>
    <details class="skill-version-source"><summary><AppIcon name="Document" :size="15" />来源与核验资料</summary>
      <template v-if="['LINK','EXTERNAL_UPLOAD'].includes(evidence.sourceType)">
        <dl><dt>来源地址</dt><dd>{{ evidence.sourceUrl||'未记录' }}</dd><dt>版本依据</dt><dd>{{ evidence.revisionKind==='CONTENT_SNAPSHOT'?'内容快照，不代表上游发布版本':'固定来源版本' }}</dd><dt>版本标识</dt><dd>{{ evidence.commit||evidence.sourceVersion||'未记录' }}</dd><dt>清单摘要</dt><dd>{{ evidence.manifestSha256||evidence.packageSha256||'未记录' }}</dd></dl>
        <p>{{ evidence.sourceType==='LINK'?'固定提交或归档及本地摘要已登记；脚本和资源只存档，不执行，不扩展工具权限。':'历史上传来源声明，未核验远端一致性，不恢复旧上传入口。' }}</p>
        <details v-for="(text,path) in licenses" :key="path" class="skill-license"><summary>{{ path }} · 许可证与版权原文</summary><pre tabindex="0" :aria-label="path+' 许可证原文'">{{ text }}</pre></details>
        <p v-if="!Object.keys(licenses).length">本记录未返回许可证原文，不据此推断已核验许可。</p>
      </template>
      <template v-else><dl><dt>来源类型</dt><dd>{{ evidence.sourceType==='RUN'?'本人授权运行':evidence.sourceType||'未记录' }}</dd><dt>成功工具记录</dt><dd>{{ Array.isArray(evidence.tools)?evidence.tools.join('、')||'无已记录工具':'未记录' }}</dd><dt>完成时间 · UTC+8</dt><dd>{{ time(evidence.completedAt) }}</dd></dl></template>
      <router-link v-if="version.sourceRunId" :to="{path:'/agent/trace',query:{runId:version.sourceRunId}}" class="skill-source-trace"><AppIcon name="Connection" :size="14" />查看本人来源轨迹</router-link>
    </details>
    <div v-if="version.reviewReason" class="skill-version-review"><strong>审核意见</strong><p>{{ version.reviewReason }}</p></div>
  </article>
</template>
<script setup>
import {computed} from 'vue'
import {beijingDateTime} from '@/utils/beijingTime'
const props=defineProps({version:{type:Object,required:true},active:Boolean,latest:Boolean})
const evidence=computed(()=>props.version.evidence||{})
const licenses=computed(()=>{const value=evidence.value.licenses;return value&&typeof value==='object'&&!Array.isArray(value)?value:{}})
const time=value=>value?beijingDateTime(value)||'时间格式未知':'未记录'
</script>
<style scoped>
.skill-version-record{margin:18px 0;padding:18px 0;border:0;border-bottom:1px solid var(--app-border);color:var(--app-text)}.skill-version-record>header{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px}.skill-version-record>header>strong{font-size:15px;font-weight:650}.skill-current-version,.skill-latest-version{font-size:11px;padding:2px 7px;border-radius:5px;background:var(--app-primary-soft);color:var(--app-primary)}.skill-latest-version{background:var(--app-info-soft);color:var(--app-text-secondary)}.skill-version-description{font-size:13px;color:var(--app-text-secondary);line-height:1.9;overflow-wrap:anywhere}.skill-version-record summary{cursor:pointer;font-size:12px;line-height:1.9;width:fit-content;color:var(--app-text-secondary)}.skill-version-record summary>.el-icon{vertical-align:middle;margin-right:5px;color:var(--app-primary)}.skill-version-record pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:280px;overflow:auto;overscroll-behavior:contain;padding:12px 14px;margin:10px 0;font-family:inherit;font-size:12px;line-height:1.9;border:1px solid var(--app-border);border-radius:8px;background:var(--app-bg);color:var(--app-text)}.skill-version-tools{margin:16px 0}.skill-version-tools h4{display:flex;align-items:center;gap:7px;font-size:12px;margin:0 0 5px;color:var(--app-text-secondary)}.skill-version-tools h4>.el-icon{color:var(--app-primary)}.skill-version-tools p,.skill-version-source p{font-size:12px;line-height:1.9;color:var(--app-text-secondary);overflow-wrap:anywhere;margin:7px 0}.skill-version-source{padding:12px 0;border-top:1px solid var(--app-border)}.skill-version-source dl{display:grid;grid-template-columns:105px minmax(0,1fr);gap:9px 14px;font-size:12px;line-height:1.85;margin:14px 0}.skill-version-source dt{color:var(--app-text-muted)}.skill-version-source dd{margin:0;min-width:0;overflow-wrap:anywhere}.skill-license{margin:10px 0}.skill-source-trace{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--app-primary);text-decoration:none;padding:8px 0}.skill-source-trace:hover{text-decoration:underline}.skill-version-review{padding:12px 14px;border-left:3px solid #acc7f6;border-radius:0 6px 6px 0;background:var(--app-primary-light);margin-top:14px}.skill-version-review strong{font-size:12px;font-weight:550}.skill-version-review p{font-size:13px;line-height:1.9;white-space:pre-wrap;margin:6px 0 0}.skill-version-record :is(summary,pre,a):focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}@media(max-width:540px){.skill-version-source dl{grid-template-columns:1fr;gap:3px}.skill-version-source dd{margin-bottom:8px}}
</style>
