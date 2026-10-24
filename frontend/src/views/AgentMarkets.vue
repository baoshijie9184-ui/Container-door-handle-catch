<template>
  <section class="market-page" aria-labelledby="market-title">
    <header class="market-header">
      <div><h2 id="market-title"><AgentSectionIcon kind="markets" />资源市场</h2><p>寻找 Agent、Skill 与 MCP 资源，核对来源后选择接入方式</p></div>
      <el-button :loading="loading" @click="refresh"><AppIcon name="Refresh" :size="16" />刷新目录</el-button>
    </header>

    <section class="market-intro" aria-label="资源目录与本系统的关系">
      <div class="market-catalog-summary"><AppIcon name="Compass" :size="22" /><div><strong>{{ catalog ? `${markets.length} 个收录平台` : loading ? '正在读取资源目录' : '平台数量尚未读取' }}</strong><p>{{ catalog?.verifiedOn ? `目录核对日期 ${catalog.verifiedOn}` : '核对日期尚未读取' }}<span v-if="catalog?.version"> · 目录版本 {{ catalog.version }}</span></p></div></div>
      <p class="integration-note">这是外部资源目录，收录与能力说明不代表已安装、通过审核或当前可连通。资源许可、账号条件和收费以来源详情为准。</p>
      <div class="market-management-links">
        <router-link to="/agent/skills"><AppIcon name="Collection" :size="18" /><span><strong>Skill 安装与审核</strong><small>从支持的公开链接下载为本人草稿</small></span><AppIcon name="ArrowRight" :size="15" /></router-link>
        <router-link to="/agent/mcp"><AppIcon name="Connection" :size="18" /><span><strong>固定 Fetch MCP</strong><small>查看本人安装、启用与执行状态</small></span><AppIcon name="ArrowRight" :size="15" /></router-link>
      </div>
      <details class="market-integration-help"><summary>如何将资源用于当前系统</summary><ul><li>Skill：当前支持公开 GitHub 目录、skills.sh 技能详情和魔搭 Skill 链接。下载后仍需评测、独立审核及发布，不执行包内脚本。</li><li>MCP：当前管理入口仅支持已登记的固定 Fetch，不支持从市场任意注册 MCP 服务。</li><li>Agent：产品、模板与托管应用需分别核对部署及兼容方式，目录不提供一键导入。</li></ul></details>
    </section>

    <section class="market-filters" aria-label="市场筛选">
      <div class="search-filters">
        <label for="market-search">平台或能力<el-input id="market-search" v-model="keyword" clearable placeholder="搜索名称、简介或能力说明" maxlength="128"><template #prefix><AppIcon name="Search" :size="16" /></template></el-input></label>
        <label for="market-region">地区<el-select id="market-region" v-model="region" aria-label="市场地区"><el-option label="全部地区" value="ALL" /><el-option label="国内" value="国内" /><el-option label="国际" value="国际" /></el-select></label>
      </div>
      <div class="type-filters" role="group" aria-label="资源类型">
        <button v-for="option in types" :key="option.value" type="button" :class="{ active:type === option.value }" :aria-pressed="type === option.value" @click="type = option.value"><AppIcon :name="option.icon" :size="16" />{{ option.label }}<span>{{ catalog ? countType(option.value) : '—' }}</span></button>
      </div>
      <div class="market-filter-footer"><label class="interface-filter"><input v-model="includeInterfaces" type="checkbox" />MCP 筛选同时包含仅提供接口的平台</label><el-button v-if="hasFilters" size="small" @click="resetFilters"><AppIcon name="Refresh" :size="14" />清空筛选</el-button></div>
    </section>

    <div class="market-result-heading"><h3>收录平台</h3><p role="status" aria-live="polite">{{ loading ? '正在读取目录' : error ? '目录读取未完成' : catalog ? `当前筛选 ${filtered.length} / ${markets.length} 个平台` : '目录尚未读取' }}</p></div>
    <p v-if="catalog" class="market-filter-note">搜索与类型数量仅覆盖本次目录，并沿用当前地区和关键词；不查询外部平台实时库存。</p>
    <TransitionGroup name="market-card" tag="div" class="market-grid" :aria-busy="loading">
      <article v-for="market in filtered" :key="market.id" class="market-item app-panel">
        <div class="card-top"><span class="market-symbol"><AppIcon :name="market.kind === '托管平台' ? 'Cpu' : 'Compass'" :size="21" /></span><span class="kind">{{ market.region }} · {{ market.kind }}</span></div>
        <h3>{{ market.name }}</h3><p class="summary">{{ market.summary || '简介尚未记录' }}</p>
        <dl class="market-capabilities"><div v-for="cap in market.capabilities" :key="cap.type"><dt><AppIcon :name="capabilityIcon(cap.type)" :size="15" />{{ capabilityName(cap.type) }}</dt><dd><StatusBadge domain="marketCapability" :code="cap.status" /></dd></div></dl>
        <div class="card-actions"><el-button @click="selected = market"><AppIcon name="Document" :size="15" />查看能力与来源</el-button><a v-if="safeUrl(market.homepage)" :href="safeUrl(market.homepage)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" :aria-label="`前往${market.name}，新窗口打开`">平台入口<AppIcon name="TopRight" :size="15" /></a><span v-else class="market-link-unavailable">入口未记录</span></div>
      </article>
    </TransitionGroup>
    <CollectionEmptyState v-if="!filtered.length" :loading="loading" :error="error" :filtered="hasFilters && !!catalog" empty-title="目录暂无可展示的平台" empty-description="可稍后重新读取目录，或前往已有 Skill 与固定 Fetch 管理入口。" @retry="refresh" @reset="resetFilters" />

    <el-dialog :model-value="!!selected" append-to-body class="agent-market-dialog" :title="selected ? `${selected.name} · 能力与接入` : '平台能力与接入'" width="min(740px, 94vw)" @close="selected = null">
      <template v-if="selected">
        <p class="market-detail-summary">{{ selected.summary || '简介尚未记录' }}</p>
        <p class="market-detail-date">目录核对日期 {{ catalog?.verifiedOn || '未记录' }}，不是实时连通性检查。</p>
        <section v-for="cap in selected.capabilities" :key="cap.type" class="capability-detail"><div class="capability-detail-heading"><h3><AppIcon :name="capabilityIcon(cap.type)" :size="17" />{{ capabilityName(cap.type) }}</h3><StatusBadge domain="marketCapability" :code="cap.status" /></div><p>{{ cap.note || '接入条件尚未记录，请核对来源。' }}</p><div class="capability-links"><template v-for="link in cap.links" :key="link.url"><a v-if="safeUrl(link.url)" :href="safeUrl(link.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" :aria-label="`${link.label}，新窗口打开`">{{ link.label }}<AppIcon name="TopRight" :size="14" /></a><span v-else class="market-link-unavailable">{{ link.label }}（入口不可用）</span></template></div></section>
        <p class="detail-note"><AppIcon name="Lock" :size="16" />浏览外部平台不改变本人已安装资源和工具权限。Skill 安装仍在技能管理中提交，普通提问不能代替敏感操作确认。</p>
        <a v-if="safeUrl(selected.sourceUrl)" class="market-source-link" :href="safeUrl(selected.sourceUrl)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">查看目录核对来源<AppIcon name="TopRight" :size="15" /></a><p v-else class="market-link-unavailable">核对来源入口未记录</p>
      </template>
      <template #footer><el-button @click="selected = null">关闭说明</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AgentSectionIcon from '@/components/chat/AgentSectionIcon.vue'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import request from '@/api/request'

const catalog = ref(null), loading = ref(false), error = ref(''), selected = ref(null)
const type = ref('ALL'), region = ref('ALL'), keyword = ref(''), includeInterfaces = ref(false)
const types = [{ value:'ALL', label:'全部平台', icon:'Compass' }, { value:'AGENT', label:'Agent 智能体', icon:'ChatDotRound' }, { value:'MCP', label:'MCP 工具', icon:'Connection' }, { value:'SKILL', label:'Skill 技能', icon:'Collection' }]
const hasFilters = computed(() => !!(keyword.value.trim() || type.value !== 'ALL' || region.value !== 'ALL' || includeInterfaces.value))
function resetFilters() { keyword.value = ''; type.value = 'ALL'; region.value = 'ALL'; includeInterfaces.value = false }
const markets = computed(() => catalog.value?.markets || [])
const capabilityName = value => types.find(item => item.value === value)?.label || '未标明类型'
const capabilityIcon = value => types.find(item => item.value === value)?.icon || 'Document'
const hasType = (market, value) => value === 'ALL' || market.capabilities.some(cap => cap.type === value && (cap.status === 'AVAILABLE' || (value === 'MCP' && includeInterfaces.value && cap.status === 'INTERFACE_ONLY')))
const searched = computed(() => {
  const term = keyword.value.trim().toLocaleLowerCase('zh-CN')
  return markets.value.filter(market => (region.value === 'ALL' || market.region === region.value) && (!term || [market.name, market.summary, market.kind, ...market.capabilities.flatMap(cap => [capabilityName(cap.type), cap.note])].join(' ').toLocaleLowerCase('zh-CN').includes(term)))
})
const countType = value => searched.value.filter(market => hasType(market, value)).length
const filtered = computed(() => searched.value.filter(market => hasType(market, type.value)))

// Fixed catalog links only; no account metadata, search terms or credentials are added.
function safeUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : undefined } catch { return undefined }
}
function readCatalog(value) {
  if (!value || !Array.isArray(value.markets)) throw new Error('市场目录未完整读取，请重新读取')
  const ids = new Set()
  for (const market of value.markets) {
    if (!market || typeof market.id !== 'string' || !market.id.trim() || ids.has(market.id) || typeof market.name !== 'string' || !market.name.trim() || typeof market.region !== 'string' || typeof market.kind !== 'string' || (market.summary != null && typeof market.summary !== 'string') || !Array.isArray(market.capabilities)) throw new Error('平台资料未完整读取，请重新读取')
    ids.add(market.id)
    const capabilities = new Set()
    for (const cap of market.capabilities) {
      if (!cap || !['AGENT','MCP','SKILL'].includes(cap.type) || capabilities.has(cap.type) || (cap.status != null && typeof cap.status !== 'string') || (cap.note != null && typeof cap.note !== 'string') || !Array.isArray(cap.links) || cap.links.some(link => !link || typeof link.label !== 'string' || typeof link.url !== 'string')) throw new Error('平台能力说明未完整读取，请重新读取')
      capabilities.add(cap.type)
    }
  }
  return value
}
let generation = 0
async function refresh() {
  if (loading.value) return
  const current = ++generation
  loading.value = true; error.value = ''; selected.value = null; catalog.value = null
  try {
    const response = await request.get('/api/agent/markets')
    if (current === generation) catalog.value = readCatalog(response.data)
  } catch (e) {
    if (current === generation) error.value = e.response?.data?.message || e.message || '市场目录暂不可用，请稍后重新读取'
  } finally { if (current === generation) loading.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => { generation++ })
</script>

<style scoped>
.market-page { max-width:1240px; margin:0 auto; color:var(--app-text); min-width:0; }
.market-header { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:22px; }
.market-header h2 { display:flex; align-items:center; gap:12px; margin:0; font-size:26px; }
.market-header p { margin:10px 0 0; color:var(--app-text-secondary); font-size:13px; line-height:1.8; }
.market-intro { padding:22px 24px; border:1px solid var(--app-border); border-radius:12px; background:white; }
.market-catalog-summary { display:flex; align-items:flex-start; gap:10px; }
.market-catalog-summary > .el-icon { margin-top:2px; color:var(--app-primary); flex-shrink:0; }
.market-catalog-summary strong { font-size:16px; font-weight:650; }
.market-catalog-summary p { margin:6px 0 0; color:var(--app-text-secondary); font-size:12px; line-height:1.8; overflow-wrap:anywhere; }
.integration-note { margin:16px 0; max-width:80ch; font-size:13px; color:var(--app-text-secondary); line-height:1.85; }
.market-management-links { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; padding:16px 0; border-block:1px solid var(--app-border); }
.market-management-links a { display:flex; align-items:center; gap:10px; min-width:0; color:var(--app-primary); text-decoration:none; }
.market-management-links a > .el-icon { flex-shrink:0; }
.market-management-links a > .el-icon:last-child { margin-left:auto; }
.market-management-links a span { display:grid; gap:5px; min-width:0; }
.market-management-links strong { font-size:13px; font-weight:600; }
.market-management-links small { font-size:12px; line-height:1.75; color:var(--app-text-secondary); }
.market-integration-help { margin-top:15px; color:var(--app-text-secondary); font-size:12px; line-height:1.85; }
.market-integration-help summary { width:fit-content; cursor:pointer; }
.market-integration-help ul { padding-left:20px; margin-bottom:0; }
.market-integration-help li + li { margin-top:7px; }
.market-filters { display:grid; gap:16px; margin-top:24px; }
.search-filters { display:grid; grid-template-columns:minmax(0,1fr) 180px; gap:14px; max-width:760px; }
.search-filters label { display:grid; gap:7px; min-width:0; color:var(--app-text-secondary); font-size:12px; }
.search-filters .el-select { width:100%; }
.type-filters { display:flex; gap:8px; flex-wrap:wrap; }
.type-filters button { display:inline-flex; align-items:center; gap:7px; border:1px solid var(--app-border); background:white; color:var(--app-text-secondary); padding:9px 12px; border-radius:8px; cursor:pointer; font:inherit; font-size:12px; line-height:1.7; transition:background 180ms ease,border-color 180ms ease,transform 160ms ease; }
.type-filters button.active { background:var(--app-primary-soft); border-color:#b7cdf9; color:var(--app-primary); }
.type-filters button:hover { border-color:#b7cdf9; }
.type-filters button:active { transform:scale(.98); }
.type-filters button span { font-variant-numeric:tabular-nums; min-width:1ch; }
.market-filter-footer { display:flex; align-items:center; flex-wrap:wrap; gap:12px; min-height:32px; }
.interface-filter { display:inline-flex; align-items:flex-start; gap:7px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; cursor:pointer; }
.interface-filter input { accent-color:var(--app-primary); margin-top:4px; }
.market-result-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:24px 0 8px; }
.market-result-heading h3 { font-size:15px; margin:0; }
.market-result-heading p,.market-filter-note { font-size:12px; line-height:1.8; color:var(--app-text-secondary); margin:0; }
.market-filter-note { margin-bottom:16px; }
.market-grid { --market-card-width:calc((100% - 36px) / 3); display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; position:relative; }
.market-item { padding:20px; border:1px solid var(--app-border); display:flex; flex-direction:column; min-width:0; }
.card-top { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.market-symbol { display:inline-grid; place-items:center; width:38px; height:38px; background:var(--app-primary-soft); color:var(--app-primary); border-radius:10px; flex-shrink:0; }
.kind { font-size:12px; line-height:1.7; color:var(--app-text-secondary); text-align:right; }
.market-item h3 { font-size:18px; line-height:1.65; margin:16px 0 7px; overflow-wrap:anywhere; }
.summary { line-height:1.85; color:var(--app-text-secondary); font-size:13px; margin:0 0 14px; overflow-wrap:anywhere; }
.market-capabilities { display:grid; gap:9px; margin:0 0 20px; }
.market-capabilities > div { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.market-capabilities dt { display:inline-flex; align-items:center; gap:7px; color:var(--app-text-secondary); font-size:12px; }
.market-capabilities dt .el-icon { color:var(--app-primary); }
.market-capabilities dd { margin:0; }
.card-actions { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; border-top:1px solid var(--app-border); padding-top:14px; margin-top:auto; }
.card-actions a { display:inline-flex; align-items:center; gap:5px; color:var(--app-primary); font-size:12px; text-decoration:none; }
.card-actions .el-button { font-size:12px; }
.market-link-unavailable { color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.market-page :is(button,a,summary,input):focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; border-radius:3px; }
.market-card-enter-active,.market-card-leave-active,.market-card-move { transition:opacity 200ms ease,transform 200ms ease; }
.market-card-enter-from,.market-card-leave-to { opacity:0; transform:translateY(6px); }
.market-card-leave-active { position:absolute; width:var(--market-card-width); box-sizing:border-box; pointer-events:none; }
@media(max-width:1100px) { .market-grid { --market-card-width:calc((100% - 18px) / 2); grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:640px) { .market-header { flex-wrap:wrap; } .market-grid { --market-card-width:100%; } .market-grid,.market-management-links { grid-template-columns:minmax(0,1fr); } .market-intro,.market-item { padding:16px; } .search-filters { grid-template-columns:minmax(0,1fr); } .market-result-heading { flex-wrap:wrap; } .market-capabilities dt { flex-wrap:wrap; } }
@media(prefers-reduced-motion:reduce) { .market-card-enter-active,.market-card-leave-active,.market-card-move,.type-filters button { transition:none; } .market-card-enter-from,.market-card-leave-to,.type-filters button:active { transform:none; } }
</style>

<style>
.agent-market-dialog .el-dialog__body { max-height:65dvh; overflow:auto; overflow-wrap:anywhere; overscroll-behavior:contain; }
.agent-market-dialog :is(.market-detail-summary,.capability-detail p) { color:var(--app-text-secondary); font-size:13px; line-height:1.85; }
.agent-market-dialog .market-detail-summary { margin-top:0; }
.agent-market-dialog .market-detail-date { margin:10px 0 20px; color:var(--app-text-secondary); font-size:12px; line-height:1.8; }
.agent-market-dialog .capability-detail { padding:16px 0; border-top:1px solid var(--app-border); }
.agent-market-dialog .capability-detail-heading { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
.agent-market-dialog h3 { display:flex; align-items:center; gap:8px; margin:0; color:var(--app-text); font-size:14px; }
.agent-market-dialog h3 .el-icon { color:var(--app-primary); }
.agent-market-dialog .capability-links { display:flex; flex-wrap:wrap; gap:10px 18px; }
.agent-market-dialog :is(.capability-links a,.market-source-link) { color:var(--app-primary); text-decoration:underline; text-underline-offset:3px; display:inline-flex; align-items:center; gap:5px; font-size:12px; line-height:1.8; }
.agent-market-dialog .detail-note { display:flex; align-items:flex-start; gap:8px; padding:12px 14px; background:var(--app-primary-soft); color:var(--app-text-secondary); font-size:12px; line-height:1.85; border-radius:8px; }
.agent-market-dialog .detail-note > .el-icon { margin-top:3px; color:var(--app-primary); flex-shrink:0; }
.agent-market-dialog .market-link-unavailable { color:var(--app-text-secondary); font-size:12px; }
.agent-market-dialog a:focus-visible { outline:2px solid var(--app-primary); outline-offset:4px; border-radius:3px; }
@media(prefers-reduced-motion:reduce) { .agent-market-dialog,.el-overlay:has(.agent-market-dialog) { animation:none!important; transition:none!important; } }
</style>
