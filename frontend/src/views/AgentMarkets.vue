<template>
  <section class="market-page" aria-labelledby="market-title">
    <header class="market-header">
      <div><p class="eyebrow">AGENT RESOURCES</p><h2 id="market-title">资源市场</h2><p>发现智能体 工具服务与可复用技能</p></div>
      <el-button :loading="loading" @click="refresh"><el-icon><Refresh /></el-icon>刷新目录</el-button>
    </header>
    <section class="market-intro app-panel">
      <div><strong>{{ markets.length }} 个平台</strong><span v-if="catalog">最近核实 {{ catalog.verifiedOn }}</span></div>
      <p>当前提供资源目录与官方入口 浏览后按资源详情选择接入方式</p>
      <p class="integration-note">经验技能支持提炼与独立审核 本地 Fetch MCP 可按账号安装启用 外部 Skill 下载与远程 Agent 接入仍待开发</p>
      <router-link to="/agent/skills">管理经验技能 <el-icon><ArrowRight /></el-icon></router-link>
      <router-link to="/agent/mcp">管理本人本地 MCP <el-icon><ArrowRight /></el-icon></router-link>
    </section>
    <section class="market-filters" aria-label="市场筛选">
      <div class="type-filters"><button v-for="option in types" :key="option.value" type="button" :class="{active: type === option.value}" :aria-pressed="type === option.value" @click="type = option.value">{{ option.label }} <span>{{ countType(option.value) }}</span></button></div>
      <div class="search-filters"><el-input v-model="keyword" clearable placeholder="搜索平台或能力" aria-label="搜索平台或能力" :prefix-icon="Search" /><el-select v-model="region" aria-label="市场地区"><el-option label="全部地区" value="ALL" /><el-option label="国内" value="国内" /><el-option label="国际" value="国际" /></el-select></div>
      <label class="interface-filter"><input v-model="includeInterfaces" type="checkbox" />包含仅提供 MCP 接口的平台</label>
    </section>
    <p v-if="error" role="alert" class="market-error">{{ error }}</p>
    <p class="result-count" role="status" aria-live="polite">{{ loading ? '正在读取目录' : '找到 ' + filtered.length + ' 个平台' }}</p>
    <TransitionGroup name="market-card" tag="div" class="market-grid" :aria-busy="loading">
      <article v-for="market in filtered" :key="market.id" class="market-item app-panel">
        <div class="card-top"><span class="market-symbol"><el-icon><component :is="market.kind === '托管平台' ? Cpu : Connection" /></el-icon></span><span class="kind">{{ market.region }} · {{ market.kind }}</span></div>
        <h3>{{ market.name }}</h3><p class="summary">{{ market.summary }}</p>
        <div class="capability-tags"><span v-for="cap in market.capabilities" :key="cap.type" :class="['capability-tag', cap.status === 'AVAILABLE' ? 'available' : 'uncertain']" :title="cap.note">{{ cap.type }} · {{ statusLabel(cap.status) }}</span></div>
        <div class="card-actions"><a :href="safeUrl(market.homepage)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" :aria-label="'前往' + market.name + ' 新窗口打开'">前往平台 <el-icon><TopRight /></el-icon></a><el-button text @click="selected = market">能力与接入说明</el-button></div>
      </article>
    </TransitionGroup>
    <el-empty v-if="!loading && !error && !filtered.length" description="没有匹配的平台 试试其他关键词或分类" />
    <el-dialog :model-value="!!selected" append-to-body class="agent-market-dialog" title="平台能力与接入说明" width="min(740px, 94vw)" @close="selected = null">
      <template v-if="selected">
        <h3>{{ selected.name }}</h3><p>{{ selected.summary }}</p>
        <section v-for="cap in selected.capabilities" :key="cap.type" class="capability-detail"><h4>{{ cap.type }} <span>{{ statusLabel(cap.status) }}</span></h4><p>{{ cap.note }}</p><a v-for="link in cap.links" :key="link.url" :href="safeUrl(link.url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{{ link.label }} <el-icon><TopRight /></el-icon></a></section>
        <p class="detail-note">市场收录不代表已接入本系统 Agent 产品或模板需核对部署方式 Skill 的许可、脚本与依赖需逐项检查 MCP 工具需明确角色与数据范围</p>
        <a :href="safeUrl(selected.sourceUrl)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">查看核实来源 <el-icon><TopRight /></el-icon></a>
      </template>
      <template #footer><el-button @click="selected = null">关闭</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowRight, Connection, Cpu, Refresh, Search, TopRight } from '@element-plus/icons-vue'
import request from '@/api/request'

const catalog = ref(null), loading = ref(false), error = ref(''), selected = ref(null)
const type = ref('ALL'), region = ref('ALL'), keyword = ref(''), includeInterfaces = ref(false)
const types = [{ value: 'ALL', label: '全部平台' }, { value: 'AGENT', label: 'Agent 智能体' }, { value: 'MCP', label: 'MCP 工具' }, { value: 'SKILL', label: 'Skill 技能' }]
const markets = computed(() => catalog.value?.markets || [])
const hasType = (market, value) => value === 'ALL' || market.capabilities.some(cap => cap.type === value && (cap.status === 'AVAILABLE' || (includeInterfaces.value && cap.status === 'INTERFACE_ONLY')))
const countType = value => markets.value.filter(market => hasType(market, value)).length
const filtered = computed(() => {
  const term = keyword.value.trim().toLowerCase()
  return markets.value.filter(market => hasType(market, type.value) && (region.value === 'ALL' || market.region === region.value) && (!term || [market.name, market.summary, market.kind, ...market.capabilities.map(cap => cap.note)].join(' ').toLowerCase().includes(term)))
})
const statusLabel = status => ({ AVAILABLE: '已核实', INTERFACE_ONLY: '仅接口', UNVERIFIED: '未核实', OUT_OF_SCOPE: '不在目录范围' }[status] || '未核实')
// 目录只导航到固定 HTTPS 入口；不拼接用户关键词、身份或密钥到外部 URL。
function safeUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : undefined } catch { return undefined }
}
let generation = 0
async function refresh() {
  const current = ++generation
  loading.value = true; error.value = ''; selected.value = null; catalog.value = null
  try {
    const response = await request.get('/api/agent/markets')
    if (current === generation) catalog.value = response.data
  } catch (e) {
    if (current === generation) error.value = e.response?.data?.message || '市场目录暂不可用 请稍后刷新'
  } finally { if (current === generation) loading.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => { generation++ })
</script>

<style scoped>
.market-page{max-width:1240px;margin:0 auto;color:#172437;min-width:0}.market-header{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:24px}.eyebrow{font-size:11px;letter-spacing:2px;color:#2463d8;font-weight:700}.market-header h2{font-size:28px;margin:8px 0}.market-header p:last-child{color:#69788c;font-size:14px}.market-intro{padding:22px 24px;border:1px solid #dbe6f8;background:linear-gradient(120deg,#fff,#f0f6ff);margin-bottom:24px}.market-intro>div{display:flex;gap:20px;align-items:center}.market-intro strong{font-size:19px}.market-intro span,.integration-note{color:#69788c;font-size:13px}.market-intro p{line-height:1.7}.market-intro a,.market-item a{color:#215fd0;text-decoration:none;font-weight:600;font-size:14px;display:inline-flex;align-items:center;gap:5px}.market-filters{display:flex;gap:16px;flex-wrap:wrap;align-items:center}.type-filters{display:flex;gap:6px;flex-wrap:wrap}.type-filters button{border:1px solid #e1e8f2;background:#fff;color:#5d6c80;padding:10px 14px;border-radius:9px;cursor:pointer;transition:background .18s,transform .18s,border-color .18s}.type-filters button.active{background:#eaf2ff;border-color:#b4cef6;color:#215fd0}.type-filters span{margin-left:5px;font-size:12px}.type-filters button:hover{transform:translateY(-1px)}.type-filters button:active{transform:scale(.98)}.type-filters button:focus-visible,a:focus-visible{outline:2px solid #2463d8;outline-offset:3px}.search-filters{display:flex;gap:10px;flex:1;min-width:270px}.search-filters .el-input{min-width:160px;flex:1}.search-filters .el-select{width:130px}.interface-filter{display:flex;align-items:center;gap:6px;font-size:13px;color:#68758b;width:100%;cursor:pointer}.result-count{font-size:13px;color:#69788c;margin:20px 0 14px}.market-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;position:relative}.market-item{padding:22px;border:1px solid #e2eaf4;display:flex;flex-direction:column;min-width:0}.card-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.market-symbol{display:flex;padding:10px;background:#edf4ff;color:#2463d8;border-radius:10px;font-size:23px}.kind{font-size:12px;color:#7b8798}.market-item h3{font-size:19px;margin:20px 0 8px}.summary{line-height:1.7;color:#69788c;font-size:14px;min-height:48px;margin:0 0 16px}.capability-tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:22px}.capability-tag{font-size:11px;padding:5px 7px;border-radius:5px;line-height:1.5}.available{color:#215fd0;background:#edf4ff}.uncertain{color:#778395;background:#f4f6f9}.card-actions{display:flex;justify-content:space-between;align-items:center;gap:8px;border-top:1px solid #edf1f6;padding-top:14px;margin-top:auto;flex-wrap:wrap}.card-actions .el-button{font-size:13px}.market-error{color:#b42318}.market-card-enter-active,.market-card-leave-active,.market-card-move{transition:opacity .2s,transform .2s}.market-card-enter-from,.market-card-leave-to{opacity:0;transform:translateY(8px)}.market-card-leave-active{position:absolute;pointer-events:none}
@media(max-width:1100px){.market-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.market-header{align-items:flex-start}.market-header h2{font-size:24px}.market-grid{grid-template-columns:1fr}.market-intro{padding:18px}.market-intro>div{flex-wrap:wrap;gap:8px}.search-filters{min-width:0;width:100%;flex:auto}.market-item{padding:18px}.type-filters button{padding:9px 10px}.market-header .el-button{margin-top:10px}}@media(prefers-reduced-motion:reduce){.market-card-enter-active,.market-card-leave-active,.market-card-move,.type-filters button{transition:none}.market-card-enter-from,.market-card-leave-to{transform:none}.type-filters button:hover,.type-filters button:active{transform:none}}
</style>
<style>
.agent-market-dialog .el-dialog__body{max-height:65vh;overflow:auto;overflow-wrap:anywhere}.agent-market-dialog h3{margin-top:0}.agent-market-dialog .capability-detail{padding:14px 0;border-bottom:1px solid #edf1f6}.agent-market-dialog h4{margin:0;color:#172437}.agent-market-dialog h4 span{font-size:12px;font-weight:400;color:#69788c;margin-left:12px}.agent-market-dialog p{color:#68758b;line-height:1.7}.agent-market-dialog a{color:#215fd0;text-decoration:none;display:inline-flex;align-items:center;gap:5px;font-size:14px}.agent-market-dialog .detail-note{padding:12px;background:#f4f7fc;font-size:13px;border-radius:8px}@media(prefers-reduced-motion:reduce){.agent-market-dialog,.el-overlay:has(.agent-market-dialog){animation:none!important;transition:none!important}}
</style>
