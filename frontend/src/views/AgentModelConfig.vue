<template>
  <main class="model-config-page" aria-labelledby="model-config-title">
    <header class="page-heading"><div><h2 id="model-config-title"><AgentSectionIcon kind="models" />Agent 模型配置</h2><p>新任务使用发布后的版本，正在执行的任务保留原版本</p></div><el-button :loading="busy" @click="refresh"><AppIcon name="Refresh" :size="16" />核对版本状态</el-button></header>
    <el-alert v-if="error&&available" :title="error" type="error" :closable="false" role="alert" />
    <p v-if="notice" role="status" class="notice">{{ notice }}</p>
    <template v-if="available && active">
      <section class="version-strip"><span>生效版本 <strong>V{{ activeRevision }}</strong></span><span>默认 {{ active.document.defaultModel }}</span><span class="memory-config-state">记忆配置<StatusBadge domain="memoryConfig" :code="active.memoryState" :label="memoryStates[active.memoryState]" /></span></section>
      <section class="version-picker"><label for="model-version">查看版本</label><el-select id="model-version" :model-value="selectedRevision" :disabled="busy" @change="selectVersion"><el-option v-for="v in versions" :key="v.revision" :value="v.revision" :label="`V${v.revision} · ${statuses[v.status] || v.status}`" /></el-select><el-button :disabled="busy" @click="editActive">编辑生效版本</el-button></section>
      <section v-if="selected" class="version-actions" aria-label="版本操作">
        <span class="selected-config-version"><strong>V{{ selected.revision }}</strong><StatusBadge domain="modelConfig" :code="selected.status" :label="statuses[selected.status]" /><small>基于 V{{ selected.baseRevision }}</small></span>
        <el-button v-if="selected.status==='DRAFT'" :disabled="busy" @click="probe">检查提炼 JSON 兼容性</el-button>
        <el-button v-if="selected.status==='DRAFT'" :disabled="busy" @click="validate">校验草稿</el-button>
        <el-button v-if="selected.status==='VALIDATED'" type="primary" :disabled="busy" @click="publish">发布此版本</el-button>
        <el-button v-if="selected.revision!==activeRevision" :disabled="busy" @click="restore">以此版本创建恢复草稿</el-button>
        <ul v-if="selected.jsonProbes?.length" class="probe-list"><li v-for="item in selected.jsonProbes" :key="item.requestId"><span>{{ item.modelId }}</span><StatusBadge domain="modelProbe" :code="item.status" :label="probeStates[item.status]" /></li></ul><p v-if="selected.jsonProbes?.length" class="config-probe-note">格式兼容检查不等同提炼质量评测，结果仅对应当前查看的版本。</p>
      </section>
      <section v-if="selected&&!editor" class="config-version-review" aria-label="所选版本配置">
        <h3>V{{ selected.revision }} 配置内容</h3>
        <p>以下为所选版本的只读记录，点击发布前请核对默认模型、备用顺序和超时。</p>
        <dl class="config-review-facts"><dt>默认模型</dt><dd>{{ selected.document.defaultModel }}</dd><dt>记忆提炼模型</dt><dd>{{ selected.document.memoryModel }}</dd><dt>备用切换</dt><dd>{{ selected.document.fallbackEnabled?'启用':'停用' }}</dd><dt>备用顺序</dt><dd><ModelConfigValue field="fallbackModels" :value="selected.document.fallbackModels" label="所选版本备用顺序" /></dd><dt>总 / 首响应超时</dt><dd>{{ selected.document.timeoutMs }} / {{ selected.document.firstTokenTimeoutMs }} ms</dd><dt>最大输出 Token</dt><dd>{{ selected.document.maxOutputTokens }}</dd></dl>
        <details class="config-recorded-models"><summary>登记的模型（{{ selected.document.models.length }} 个）</summary><ModelConfigValue field="models" :value="selected.document.models" label="所选版本模型登记" /></details>
        <ModelConfigDiff :before="active.document" :after="selected.document" />
      </section>
      <el-form v-if="editor" :model="editor" label-position="top" class="config-editor" @submit.prevent="saveDraft">
        <h3>配置草稿 <small>基于 V{{ baseRevision }}</small></h3>
        <p v-if="draftDirty" class="config-draft-note" role="status"><AppIcon name="Edit" :size="15" />有尚未保存到服务器的修改，保存草稿后仍需校验和发布。</p>
        <p v-if="baseRevision!==activeRevision" class="config-draft-note" role="status">生效版本已变为 V{{ activeRevision }}，本页仍保留基于 V{{ baseRevision }} 的修改；请先复制需要保留的内容，再重新编辑生效版本。</p>
        <div class="model-rows" tabindex="0" role="region" aria-label="本草稿模型登记，可滚动阅读"><div v-for="(model,index) in editor.models" :key="model.id" class="model-row"><el-checkbox v-model="model.enabled" :disabled="busy" :aria-label="`启用 ${model.id}`">{{ model.id }}</el-checkbox><el-button text :disabled="busy || editor.models.length===1" :aria-label="`从本草稿移出 ${model.id}`" @click="removeModel(index)">移出草稿</el-button></div></div>
        <div class="add-model"><el-select v-model="newProvider" aria-label="接入类型" :disabled="busy"><el-option v-for="(label,id) in providers" :key="id" :value="id" :label="label" /></el-select><el-input v-model="newModel" placeholder="填写供应商模型名" aria-label="新模型名称" :disabled="busy" maxlength="128" @keydown.enter.prevent="addModel" /><el-button :disabled="busy || !newModel.trim()" @click="addModel">加入列表</el-button></div>
        <div class="form-grid">
          <el-form-item label="默认模型"><el-select v-model="editor.defaultModel" :disabled="busy" aria-label="默认模型"><el-option v-for="m in enabled" :key="m.id" :value="m.id" :label="m.id" /></el-select></el-form-item>
          <el-form-item label="提炼候选模型"><el-select v-model="editor.memoryModel" :disabled="busy" aria-label="提炼候选模型"><el-option v-for="m in memoryCandidates" :key="m.id" :value="m.id" :label="m.id" /></el-select><small>更换连接后须保存草稿并通过 JSON 检查，才能发布</small></el-form-item>
          <el-form-item label="总超时（毫秒）"><el-input-number v-model="editor.timeoutMs" :min="1000" :max="3600000" :step="1000" :disabled="busy" /></el-form-item>
          <el-form-item label="首响应超时（毫秒）"><el-input-number v-model="editor.firstTokenTimeoutMs" :min="1000" :max="editor.timeoutMs" :step="1000" :disabled="busy" /></el-form-item>
          <el-form-item label="最大输出 Token"><el-input-number v-model="editor.maxOutputTokens" :min="16" :max="65536" :disabled="busy" /></el-form-item>
          <el-form-item label="供应商备用切换"><el-switch v-model="editor.fallbackEnabled" :disabled="busy" aria-label="启用备用模型" /></el-form-item>
        </div>
        <div class="fallback-order"><h4>备用顺序</h4><p v-if="!editor.fallbackModels.length">尚未设置备用模型</p><ol><li v-for="(id,index) in editor.fallbackModels" :key="id"><small class="fallback-position" :aria-label="'备用顺序 '+(index+1)">{{ index+1 }}</small><span>{{ id }}</span><el-button text :disabled="busy || index===0" :aria-label="`上移 ${id}`" @click="moveFallback(index,-1)">上移</el-button><el-button text :disabled="busy || index===editor.fallbackModels.length-1" :aria-label="`下移 ${id}`" @click="moveFallback(index,1)">下移</el-button><el-button text :disabled="busy" :aria-label="`移出备用 ${id}`" @click="editor.fallbackModels.splice(index,1)">移出备用</el-button></li></ol><el-select v-model="fallbackToAdd" placeholder="选择要追加的备用模型" aria-label="追加备用模型" :disabled="busy" @change="addFallback"><el-option v-for="m in availableFallbacks" :key="m.id" :value="m.id" :label="m.id" /></el-select></div>
        <section class="credentials"><h4>连接凭证</h4><p>仅写入替换值。留空保留现有凭证，服务器不回传 Key。</p><div v-for="(label,id) in providers" :key="id" class="credential-row"><el-form-item :label="`${label} · ${active.credentials[id]?'已配置':'未配置或已撤销'}`"><el-input v-model="keys[id]" type="password" autocomplete="new-password" :disabled="busy" :aria-label="`${label} 新 API Key`" placeholder="留空保留现有凭证" /></el-form-item><el-button :disabled="busy || !active.credentials[id]" type="danger" plain @click="revoke(id)">撤销现有 Key</el-button></div></section>
        <ModelConfigDiff :before="active.document" :after="editor" next-label="本次草稿值"><p v-if="Object.values(keys).some(Boolean)">包含凭证替换，值已隐藏</p></ModelConfigDiff>
        <el-button type="primary" native-type="submit" :loading="busy">保存为新草稿</el-button>
      </el-form>
    </template>
    <CollectionEmptyState v-else :loading="busy" :error="error" empty-title="模型配置尚未读取" empty-description="请核对当前账号授权及服务状态，读取成功后再操作配置。" @retry="refresh" />
  </main>
</template>

<script setup>
import AgentSectionIcon from "@/components/chat/AgentSectionIcon.vue"
import {computed,onMounted,ref,onBeforeUnmount} from 'vue'
import {onBeforeRouteLeave} from 'vue-router'
import {ElMessageBox} from 'element-plus'
import request from '@/api/request'
import {readModelConfiguration} from '@/utils/modelConfigResponse'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import ModelConfigDiff from '@/components/chat/ModelConfigDiff.vue'
import ModelConfigValue from '@/components/chat/ModelConfigValue.vue'
const providers={dashscope:'百炼',deepseek:'DeepSeek 直连',openai:'灵算 Responses'}
const statuses={DRAFT:'待校验',VALIDATED:'已校验，待发布',PUBLISHED:'已发布',RETIRED:'历史版本'}
const memoryStates={ENVIRONMENT:'沿用部署配置',PENDING:'应用中，需核对',APPLIED:'已应用'}
const probeStates={PASSED:'格式兼容通过',FAILED:'未通过，不自动重试',STARTED:'结果待核对，不自动重试'}
const versions=ref([]),activeRevision=ref(0),selectedRevision=ref(0),editor=ref(null),baseRevision=ref(0)
const available=ref(false)
const keys=ref({dashscope:'',deepseek:'',openai:''}),busy=ref(false),error=ref(''),notice=ref('')
const newProvider=ref('dashscope'),newModel=ref(''),fallbackToAdd=ref('')
const editorBaseline=ref('')
const active=computed(()=>versions.value.find(v=>v.revision===activeRevision.value))
const selected=computed(()=>versions.value.find(v=>v.revision===selectedRevision.value))
const enabled=computed(()=>editor.value?.models.filter(m=>m.enabled)||[])
const memoryCandidates=computed(()=>enabled.value.filter(m=>!m.id.startsWith('openai-official:')))
const availableFallbacks=computed(()=>enabled.value.filter(m=>!editor.value.fallbackModels.includes(m.id)))
const draftDirty=computed(()=>!!editor.value&&(JSON.stringify(editor.value)!==editorBaseline.value||Object.values(keys.value).some(Boolean)||!!newModel.value.trim()))
// Only in-memory request receipts; never store credentials in browser storage.
const pending=new Map()
function clearKeys(){keys.value={dashscope:'',deepseek:'',openai:''}}
async function command(path,payload){if(!available.value)throw Error('模型配置尚未核对');const bytes=new TextEncoder().encode(JSON.stringify([path,payload]));const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');if(!pending.has(hash))pending.set(hash,crypto.randomUUID());return (await request.post('/api/agent/model-config'+path,{...payload,requestId:pending.get(hash)},{headers:{'X-Model-Action':'update'},timeout:25000})).data}
async function readVersions(){try{const data=readModelConfiguration((await request.get('/api/agent/model-config')).data);versions.value=data.versions;activeRevision.value=data.activeRevision;if(!selectedRevision.value||!versions.value.some(v=>v.revision===selectedRevision.value))selectedRevision.value=data.activeRevision;available.value=true}catch(error){available.value=false;clearKeys();throw error}}
async function refresh(){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{await readVersions();if(!editor.value&&!editorBaseline.value)loadActiveEditor();notice.value='已核对服务器配置状态，未重复提交操作'}catch(e){error.value=e.response?.data?.message||'模型管理暂不可用，请核对主管权限、服务开关及前后端版本'}finally{busy.value=false}}
function loadActiveEditor(){if(!active.value)return;baseRevision.value=activeRevision.value;selectedRevision.value=activeRevision.value;editor.value=JSON.parse(JSON.stringify(active.value.document));editorBaseline.value=JSON.stringify(editor.value);newModel.value='';fallbackToAdd.value='';clearKeys()}
async function confirmDiscard(){if(!draftDirty.value)return true;try{await ElMessageBox.confirm('当前模型策略或新凭证尚未保存，继续将丢弃本页修改。凭证不会保存在浏览器中。','离开未保存的配置',{type:'warning',confirmButtonText:'丢弃修改',cancelButtonText:'继续编辑'});return true}catch{return false}}
async function editActive(){if(busy.value||!await confirmDiscard())return;loadActiveEditor()}
async function selectVersion(revision){if(busy.value||revision===selectedRevision.value||!await confirmDiscard())return;selectedRevision.value=revision;clearKeys();editor.value=null;newModel.value='';fallbackToAdd.value=''}
function addModel(){const name=newModel.value.trim();if(!/^[A-Za-z0-9][A-Za-z0-9._/\-]{0,127}$/.test(name)){error.value='模型名格式无效';return}const id=(newProvider.value==='openai'?'openai-official':newProvider.value)+':'+name;if(editor.value.models.some(m=>m.id===id)){error.value='此模型已登记';return}editor.value.models.push({id,enabled:true});newModel.value='';error.value=''}
function removeModel(index){const [removed]=editor.value.models.splice(index,1);editor.value.fallbackModels=editor.value.fallbackModels.filter(id=>id!==removed.id)}
function addFallback(id){if(id&&!editor.value.fallbackModels.includes(id))editor.value.fallbackModels.push(id);fallbackToAdd.value=''}
function moveFallback(index,offset){const list=editor.value.fallbackModels;[list[index],list[index+offset]]=[list[index+offset],list[index]]}
async function run(action,success){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{await action();await readVersions();notice.value=success}catch(e){if(e!=='cancel'&&e!=='close')error.value=e.response?.data?.message||'操作结果尚未核对，请先核对服务器版本状态；不会自动重试'}finally{busy.value=false}}
async function saveDraft(){if(busy.value||!editor.value)return;const apiKeys=Object.fromEntries(Object.entries(keys.value).filter(([,value])=>value));await run(async()=>{const saved=await command('/drafts',{baseRevision:baseRevision.value,document:editor.value,apiKeys});selectedRevision.value=saved.revision;editor.value=null;newModel.value='';fallbackToAdd.value=''},'草稿已保存，校验并确认发布后生效');clearKeys()}
function sameSelection(revision){if(!busy.value&&selected.value?.revision===revision)return true;notice.value='查看的版本已变化，本次确认未提交，请核对后重新操作';return false}
async function probe(){const revision=selected.value?.revision,modelId=selected.value?.document.memoryModel;if(busy.value||!revision)return;try{await ElMessageBox.confirm(`向 V${revision} 的提炼模型 ${modelId} 发送一次短 JSON 请求，可能消耗供应商额度。失败或断网不会自动重试。`,'单次兼容检查',{confirmButtonText:'确认单次检查',cancelButtonText:'取消'});if(sameSelection(revision))await run(()=>command(`/${revision}/json-probe`,{modelId}),'检查已结束，请查看版本检查回执')}catch{}}
async function validate(){await run(()=>command(`/${selected.value.revision}/validate`,{}),'草稿已校验，请审阅配置后发布')}
async function publish(){const revision=selected.value?.revision;if(busy.value||!revision)return;try{await ElMessageBox.confirm(`发布 V${revision}？新任务使用此配置，原任务继续使用已固定的版本。`,'发布模型配置',{confirmButtonText:`发布 V${revision}`,cancelButtonText:'继续审阅'});if(sameSelection(revision))await run(()=>command(`/${revision}/publish`,{}),'模型配置已发布，请核对记忆配置应用状态')}catch{}}
async function restore(){const revision=selected.value?.revision;if(busy.value||!revision||!await confirmDiscard()||!sameSelection(revision))return;await run(async()=>{const saved=await command(`/${revision}/restore`,{baseRevision:activeRevision.value});selectedRevision.value=saved.revision;editor.value=null;newModel.value='';fallbackToAdd.value='';clearKeys()},'已创建恢复草稿，沿用当前凭证，仍须校验发布')}
async function revoke(provider){const revision=activeRevision.value;if(busy.value)return;try{await ElMessageBox.confirm(`撤销${providers[provider]}当前 Key？引用此凭证的历史任务也将无法继续调用，请先核对影响。`,'撤销连接凭证',{type:'warning',confirmButtonText:'撤销现有 Key',cancelButtonText:'保留凭证'});if(busy.value||revision!==activeRevision.value){notice.value='生效版本已变化，本次撤销未提交，请重新核对';return}await run(()=>command(`/credentials/${provider}/revoke`,{revision}),'凭证已撤销，请配置替换值并发布')}catch{}}
onBeforeRouteLeave(async()=>{if(busy.value){notice.value='正在等待配置操作回执，请先留在本页核对结果';return false}return await confirmDiscard()})
onMounted(refresh)
onBeforeUnmount(()=>{clearKeys();pending.clear()})
</script>

<style scoped>
.model-config-page{max-width:1100px;margin:auto;padding:24px;background:#fff;border:1px solid #e5eaf2;border-radius:18px;animation:config-enter .18s ease}.page-heading{display:flex;justify-content:space-between;align-items:center;gap:16px}.page-heading h2{margin:0}.page-heading p,.credentials p{font-size:13px;color:#64748b}.version-strip{display:flex;gap:16px;flex-wrap:wrap;padding:16px;margin:18px 0;border-radius:12px;background:#f3f7ff;font-size:13px}.version-picker,.version-actions{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:16px 0}.version-picker .el-select{width:240px}.version-actions>span{font-size:13px;color:#475569}.probe-list{flex-basis:100%;margin:4px 0;padding-left:22px;font-size:13px;color:#475569}.config-editor{border-top:1px solid #e5eaf2;padding-top:16px}.config-editor h3 small{font-weight:400;color:#64748b;font-size:13px;margin-left:8px}.model-rows{max-height:260px;overflow:auto;border:1px solid #e5eaf2;border-radius:10px;padding:8px 12px}.model-rows:focus-visible{outline:2px solid var(--app-primary);outline-offset:3px}.version-strip>span{min-width:0;overflow-wrap:anywhere;line-height:1.85}.fallback-order .fallback-position{flex:none;min-width:22px;font-size:12px;line-height:22px;text-align:center;border-radius:5px;background:var(--app-primary-soft);color:var(--app-primary)}.model-row{display:flex;justify-content:space-between;align-items:center;gap:8px;overflow-wrap:anywhere}.model-row :deep(.el-checkbox__label){white-space:normal;overflow-wrap:anywhere}.add-model{display:grid;grid-template-columns:180px minmax(0,1fr) auto;gap:8px;margin:12px 0 24px}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 24px}.form-grid .el-select{width:100%}.form-grid small{color:#64748b;line-height:1.6}.fallback-order{padding:12px 0}.fallback-order ol{padding-left:24px}.fallback-order li{display:flex;align-items:center;flex-wrap:wrap;gap:6px;font-size:13px}.fallback-order li>span{flex:1;min-width:120px;overflow-wrap:anywhere}.fallback-order>.el-select{width:min(100%,420px)}h4{margin:8px 0 12px}.credentials{margin:20px 0}.credential-row{display:flex;gap:16px;align-items:center}.credential-row .el-form-item{flex:1;min-width:0}.notice{color:#1d4ed8;font-size:13px}.empty-state{padding:32px;color:#64748b}button{transition:transform .15s ease}button:active{transform:scale(.98)}@keyframes config-enter{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}@media(max-width:680px){.model-config-page{padding:14px}.page-heading{align-items:flex-start;flex-direction:column}.form-grid{grid-template-columns:1fr}.add-model{grid-template-columns:1fr}.credential-row{align-items:stretch;flex-direction:column;gap:0;margin-bottom:16px}.version-strip{gap:10px}.version-picker .el-select{max-width:100%}}@media(prefers-reduced-motion:reduce){.model-config-page,button{animation:none;transition:none;transform:none}}
</style>
