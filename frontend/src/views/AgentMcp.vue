<template>
  <section class="mcp-page app-panel">
    <header><div><h2>MCP 工具</h2><p>按账号安装与启用 由 AgentScope 通过受控运行环境调用</p></div><el-button :loading="loading" @click="refresh">刷新状态</el-button></header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template v-if="state">
      <article class="server-card"><div class="server-title"><el-icon><Connection /></el-icon><h3>{{ state.name }}</h3><el-tag>{{ statusLabel(state.status) }}</el-tag></div>
        <p>固定版本 {{ state.version }} · MIT · {{ state.transport }}</p><p>本人文件目录 <code>{{ state.directory }}</code></p>
        <p v-if="state.transport==='STREAMABLE_HTTP'">通过 AI 网关调用隔离容器 本人目录保存版本登记 包与许可证保留在固定运行镜像中</p><p v-else>包与依赖、隔离 Python 环境、版本清单及许可证保留在本人后端 Agent 目录 其他账号独立安装</p><p v-if="state.requiresMigration" class="error">运行环境已更新 请重新确认固定版本后启用</p>
        <p v-if="state.status==='PENDING_CONFIRM'">助手已提出安装提议 尚未下载或执行 请核对来源和许可证后确认</p>
        <p v-if="state.status==='INSTALLING'" role="status">正在后台准备运行环境并检查 MCP 握手 安装后仍需主动启用 可稍后刷新</p>
        <p v-if="state.status==='INSTALLING'&&state.installQueue==='DURABLE'&&state.installPhase==='QUEUED'" role="status">已保存安装任务，正在等待执行；服务重启后可在确认有效期内恢复等待任务。</p>
        <p v-if="state.status==='INSTALLING'&&state.installQueue==='DURABLE'&&state.installPhase==='RUNNING'" role="status">已开始执行安装；若服务中断，不会自动重复安装。超时后请核对状态，再重新确认。</p>
        <p v-if="state.status==='CANCELLED'" role="status">本次安装登记已撤销，不会自动启用。后台执行会尽力中断，已有文件保留；重新安装需再次确认来源与许可证。</p>
        <p v-if="state.status==='UNINSTALLED'" role="status">本人安装登记已移除，助手不能调用此工具。已有文件与审计保留，未释放磁盘空间；再次使用需重新确认安装。</p>
        <p v-if="state.errorCode" class="error">{{ state.errorCode }} · 安装失败不会启用 {{ state.transport==='STREAMABLE_HTTP'?'请刷新状态并联系管理员检查网关服务':'请检查本人目录内 install.log' }}</p>
        <div class="actions"><el-button v-if="['NOT_INSTALLED','PENDING_CONFIRM','ERROR','CANCELLED','UNINSTALLED'].includes(state.status)||state.requiresMigration" type="primary" :disabled="busy" @click="openInstall">安装到我的 Agent 目录</el-button><el-button v-if="state.status==='INSTALLING'&&state.operationId" :disabled="busy" @click="cancelInstallation">取消本次安装</el-button><el-button v-if="state.status==='INSTALLED'&&!state.requiresMigration" :disabled="busy" @click="probe">测试 MCP 连接</el-button><el-button v-if="state.status==='INSTALLED'&&(state.enabled||!state.requiresMigration)" :type="state.enabled?'default':'primary'" :disabled="busy" @click="toggle">{{ state.enabled?'停用本人 MCP':'启用本人 MCP' }}</el-button><el-button v-if="state.status==='INSTALLED'&&state.operationId&&state.registrationRemovalSupported===true" :disabled="busy||state.enabled" @click="removeRegistration">移除安装登记</el-button></div>
        <p v-if="state.status==='INSTALLED'&&state.enabled&&state.registrationRemovalSupported===true">移除安装登记前，请先停用本人 MCP</p>
        <p v-if="state.status==='INSTALLED'&&!state.requiresMigration">{{ state.enabled?'已启用 后续助手可读取你明确提供的公开网页':'尚未启用 助手不能调用' }}  · 每次调用结束清理运行环境 停用会关闭当前连接</p>
        <p v-if="probeResult" role="status">{{ probeResult }}</p>
        <a :href="state.sourceUrl" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">查看魔搭服务详情</a>
      </article>
      <section v-if="state.manifest" class="files-panel"><h3>运行文件清单</h3><p>包摘要 {{ state.manifest.packageSha256 }}</p><el-table :data="state.manifest.artifacts || []"><el-table-column prop="name" label="依赖" min-width="160"/><el-table-column prop="version" label="固定版本" min-width="130"/><el-table-column prop="path" label="包内相对路径" min-width="230"/></el-table><p>许可证/版权文件 {{ state.manifest.licenses?.length || 0 }} 份 · 依赖摘要记录在安装清单中 网关模式的依赖包和许可证保留在隔离运行镜像内</p></section>
      <section class="audit-panel"><h3>本人操作审计</h3><el-empty v-if="!state.audit.length" description="暂无 MCP 操作"/><p v-for="(event,index) in state.audit" :key="index">{{ event.action_name }} · {{ event.outcome }} · {{ event.created_at }}<router-link v-if="event.run_id" :to="{path:'/agent/trace',query:{runId:event.run_id}}">查看本人运行</router-link></p></section>
    </template>
    <el-dialog v-model="installOpen" append-to-body class="local-mcp-dialog" title="确认安装 Fetch MCP" width="min(720px,94vw)" :close-on-click-modal="false" :show-close="!busy">
      <template v-if="state"><p>安装 mcp-server-fetch {{ state.version }}。网关模式登记已核对的隔离运行镜像，本地模式创建专属 Python 环境。两者都检查 MCP 握手，安装完成保持未启用。</p><p>存储 {{ state.directory }}/installs/安装编号</p><p>此处仅安装已核对的固定 Fetch 包 不执行自定义命令</p><a href="https://pypi.org/project/mcp-server-fetch/2026.10.10/" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">核对版本与许可</a><el-checkbox v-model="licenseAccepted" :disabled="busy">我确认安装此固定版本并已核对 MIT 许可证</el-checkbox></template>
      <p v-if="dialogError" class="error" role="alert">{{ dialogError }}</p>
      <template #footer><el-button :disabled="busy" @click="installOpen=false">取消</el-button><el-button type="primary" :disabled="!licenseAccepted" :loading="busy" @click="install">确认安装</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { ref,onMounted,onBeforeUnmount } from 'vue'
import { Connection } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import request from '@/api/request'
const state=ref(null),loading=ref(false),busy=ref(false),error=ref(''),dialogError=ref(''),probeResult=ref(''),installOpen=ref(false),licenseAccepted=ref(false)
const headers={'X-MCP-Action':'update'}
let generation=0,timer=null,requestId=''
let mounted=true,cancelPromptOpen=false,removePromptOpen=false
const statusLabel=value=>({NOT_INSTALLED:'未安装',PENDING_CONFIRM:'待本人确认',INSTALLING:'安装中',INSTALLED:'已安装',ERROR:'安装失败',CANCELLED:'已取消安装',UNINSTALLED:'已移除登记'}[value]||value)
async function refresh(){const n=++generation;loading.value=true;error.value='';clearTimeout(timer);try{const result=await request.get('/api/agent/mcp/fetch');if(n!==generation)return;state.value=result.data;if(state.value.status==='INSTALLING')timer=setTimeout(refresh,4000)}catch(e){if(n===generation){state.value=null;error.value=e.response?.data?.message||'本地 MCP 尚未启用或服务暂不可用'}}finally{if(n===generation)loading.value=false}}
function openInstall(){licenseAccepted.value=false;dialogError.value='';requestId=crypto.randomUUID();installOpen.value=true}
async function install(){if(busy.value)return;busy.value=true;dialogError.value='';try{state.value=(await request.post('/api/agent/mcp/fetch/install',{expectedRevision:state.value.revision,requestId,licenseAccepted:licenseAccepted.value},{headers})).data;installOpen.value=false;await refresh()}catch(e){dialogError.value=e.response?.data?.message||'安装结果尚未核实 请刷新状态后核对'}finally{busy.value=false}}
async function probe(){busy.value=true;probeResult.value='';try{const result=await request.post('/api/agent/mcp/fetch/probe',null,{headers,timeout:30000});probeResult.value=result.data.connected?'MCP 握手成功 已发现 fetch 工具':'连接未完成';await refresh()}catch(e){error.value=e.response?.data?.message||'MCP 连接失败'}finally{busy.value=false}}
async function cancelInstallation(){
  if(busy.value||state.value?.status!=='INSTALLING'||!state.value.operationId)return
  const operationId=state.value.operationId, expectedRevision=state.value.revision
  busy.value=true;error.value='';clearTimeout(timer);generation++;loading.value=false;cancelPromptOpen=true
  try{
    await ElMessageBox.confirm('撤销本次安装登记，并尝试中断后台执行。已有文件保留，不会启用工具；若安装已完成，将拒绝取消。','确认取消安装',{confirmButtonText:'确认取消安装',cancelButtonText:'继续等待',closeOnClickModal:false})
    cancelPromptOpen=false
    if(!mounted)return
    await request.post('/api/agent/mcp/fetch/install/cancel',{operationId,expectedRevision,confirmed:true},{headers})
    if(mounted)await refresh()
  }catch(e){if(mounted&&e!=='cancel'&&e!=='close')error.value=e.response?.data?.message||'取消结果尚未核实，请刷新状态核对，不会自动重试'}
  finally{cancelPromptOpen=false;if(mounted){busy.value=false;if(state.value?.status==='INSTALLING')timer=setTimeout(refresh,4000)}}
}
async function removeRegistration(){
  if(busy.value||state.value?.status!=='INSTALLED'||state.value.enabled||!state.value.operationId||state.value.registrationRemovalSupported!==true)return
  const operationId=state.value.operationId,expectedRevision=state.value.revision
  busy.value=true;error.value='';clearTimeout(timer);generation++;loading.value=false;removePromptOpen=true
  try{
    await ElMessageBox.confirm('仅移除本人的 Fetch 安装登记，助手将不能调用。已有文件、许可证与审计保留，不释放磁盘空间；重新使用需再次确认安装。','确认移除安装登记',{confirmButtonText:'确认移除登记',cancelButtonText:'保留登记',closeOnClickModal:false})
    removePromptOpen=false
    if(!mounted)return
    await request.post('/api/agent/mcp/fetch/registration/remove',{operationId,expectedRevision,confirmed:true},{headers})
    if(mounted){probeResult.value='';await refresh()}
  }catch(e){if(mounted&&e!=='cancel'&&e!=='close')error.value=e.response?.data?.message||'移除结果尚未核实，请刷新状态核对，不会自动重试'}
  finally{removePromptOpen=false;if(mounted)busy.value=false}
}
async function toggle(){const enabled=!state.value.enabled;try{await ElMessageBox.confirm(enabled?'启用后助手可按你明确提供的公开网页地址调用 此配置仅属于当前账号':'停用会关闭本人当前 MCP 连接 后续调用将拒绝','确认 MCP 状态变更',{confirmButtonText:enabled?'确认启用':'确认停用',cancelButtonText:'取消'});busy.value=true;state.value=(await request.post('/api/agent/mcp/fetch/enabled',{expectedRevision:state.value.revision,enabled},{headers})).data;await refresh()}catch(e){if(e!=='cancel'&&e!=='close')error.value=e.response?.data?.message||'状态变更尚未核实 请刷新后核对'}finally{busy.value=false}}
onMounted(refresh);onBeforeUnmount(()=>{mounted=false;generation++;clearTimeout(timer);if(cancelPromptOpen||removePromptOpen)ElMessageBox.close()})
</script>
<style scoped>
.mcp-page{padding:24px;border-radius:16px;background:#fff;border:1px solid #e3eaf5}.mcp-page header,.server-title,.actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.mcp-page header{justify-content:space-between}.server-card,.files-panel,.audit-panel{margin:20px 0;padding:20px;background:#f7faff;border:1px solid #dce7f7;border-radius:12px}.mcp-page p{font-size:13px;line-height:1.8;color:#64748b;overflow-wrap:anywhere}.mcp-page a{color:#2563eb;margin-left:8px}.server-title>.el-icon{font-size:24px;color:#2563eb}.error{color:#b42318!important}.mcp-page :deep(button){transition:transform .15s ease}.mcp-page :deep(button:hover:not(:disabled)){transform:scale(1.02)}@media(prefers-reduced-motion:reduce){.mcp-page :deep(button){transition:none;transform:none!important}}@media(max-width:600px){.mcp-page{padding:12px}.server-card,.files-panel,.audit-panel{padding:12px}}
</style>
<style>
.local-mcp-dialog .el-dialog__body{max-height:65vh;overflow:auto}.local-mcp-dialog p{font-size:13px;line-height:1.8;overflow-wrap:anywhere}.local-mcp-dialog .el-checkbox{margin-top:18px;height:auto}.local-mcp-dialog .el-checkbox__label{white-space:normal;line-height:1.8}.local-mcp-dialog .error{color:#b42318}
</style>
