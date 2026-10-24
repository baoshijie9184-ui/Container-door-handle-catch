<template>
  <section class="mcp-page app-panel">
    <header><div><h2><AgentSectionIcon kind="mcp" />MCP 工具</h2><p>按账号安装与启用 由 AgentScope 通过受控运行环境调用</p></div><el-button :loading="loading" @click="refresh"><AppIcon name="Refresh" :size="16" />刷新状态</el-button></header>
    <p v-if="error&&state" class="error" role="alert">{{ error }}</p>
    <AgentLifecycleGuide label="固定 Fetch 工具从安装到执行清理的流程" :steps="mcpStages" />
    <CollectionEmptyState v-if="!state" :loading="loading" :error="error" empty-title="MCP 状态尚未读取" empty-description="请先读取当前账号的固定 Fetch 登记，不根据空资料推断已经安装或未安装。" @retry="refresh" />
    <template v-if="state">
      <p v-if="state.writesEnabled===false" class="execution-panel" role="status">MCP 新安装和新执行已暂停 可以查看历史、停用工具、取消安装及核对原执行退出</p>
      <article class="server-card"><div class="server-title"><el-icon><Connection /></el-icon><h3>{{ state.name }}</h3><StatusBadge domain="mcpInstallation" :code="state.status" :label="statusLabel(state.status)" /><StatusBadge v-if="state.status==='INSTALLED' && typeof state.enabled==='boolean'" domain="mcpEnabled" :code="state.enabled ? 'ENABLED' : 'DISABLED'" /></div>
        <p class="server-purpose">读取你明确提供的公开网页，调用仍受当前账号权限与工具范围限制</p>
        <details class="agent-technical-disclosure"><summary><AppIcon name="Document" :size="15" />版本、来源与存储说明<AppIcon name="ArrowDown" :size="13" class="technical-chevron" /></summary><p>固定版本 {{ state.version }} · MIT · {{ state.transport }}</p><p>本人文件目录 <code>{{ state.directory }}</code></p><p v-if="state.transport==='STREAMABLE_HTTP'">通过 AI 网关调用隔离容器 本人目录保存版本登记 包与许可证保留在固定运行镜像中</p><p v-else>包与依赖、隔离 Python 环境、版本清单及许可证保留在本人后端 Agent 目录 其他账号独立安装</p></details><p v-if="state.requiresMigration" class="error">运行环境已更新 请重新确认固定版本后启用</p>
        <p v-if="state.status==='PENDING_CONFIRM'">助手已提出安装提议 尚未下载或执行 请核对来源和许可证后确认</p>
        <p v-if="state.status==='INSTALLING'" role="status">正在后台准备运行环境并检查 MCP 握手 安装后仍需主动启用 可稍后刷新</p>
        <p v-if="state.status==='INSTALLING'&&state.installQueue==='DURABLE'&&state.installPhase==='QUEUED'" role="status">已保存安装任务，正在等待执行；服务重启后可在确认有效期内恢复等待任务。</p>
        <p v-if="state.status==='INSTALLING'&&state.installQueue==='DURABLE'&&state.installPhase==='RUNNING'" role="status">已开始执行安装；若服务中断，不会自动重复安装。超时后请核对状态，再重新确认。</p>
        <p v-if="state.status==='CANCELLED'" role="status">本次安装登记已撤销，不会自动启用。后台执行会尽力中断，已有文件保留；重新安装需再次确认来源与许可证。</p>
        <p v-if="state.status==='UNINSTALLED'" role="status">本人安装登记已移除，助手不能调用此工具。已有文件与审计保留，未释放磁盘空间；再次使用需重新确认安装。</p>
        <p v-if="state.errorCode" class="error">{{ state.errorCode }} · {{ state.status==='INSTALLED'?'上次安装未启用 已保留原版本 请核对后手动启用':'安装未完成 不会自动启用 请刷新核对' }}</p>
        <div class="actions"><el-button v-if="state.status!=='INSTALLING'&&(['NOT_INSTALLED','PENDING_CONFIRM','ERROR','CANCELLED','UNINSTALLED'].includes(state.status)||state.requiresMigration||state.upgradeAvailable)" type="primary" :disabled="busy||state.writesEnabled===false" @click="openInstall">{{ state.status==='INSTALLED'?'升级到已批准版本':'安装到我的 Agent 目录' }}</el-button><el-button v-if="state.status==='INSTALLING'&&state.operationId" :disabled="busy" @click="cancelInstallation">取消本次安装</el-button><el-button v-if="state.status==='INSTALLED'&&!state.requiresMigration" :disabled="busy||state.writesEnabled===false" @click="probe">测试 MCP 连接</el-button><el-button v-if="state.status==='INSTALLED'&&(state.enabled||!state.requiresMigration)" :type="state.enabled?'default':'primary'" :disabled="busy||state.writesEnabled===false&&!state.enabled" @click="toggle">{{ state.enabled?'停用本人 MCP':'启用本人 MCP' }}</el-button><el-button v-if="state.status==='INSTALLED'&&state.operationId&&state.registrationRemovalSupported===true" :disabled="busy||state.enabled" @click="removeRegistration">移除安装登记</el-button></div>
        <p v-if="state.status==='INSTALLED'&&state.enabled&&state.registrationRemovalSupported===true">移除安装登记前，请先停用本人 MCP</p>
        <p v-if="state.status==='INSTALLED'&&!state.requiresMigration">{{ state.enabled?'已启用 后续助手可读取你明确提供的公开网页':'尚未启用 助手不能调用' }} · 调用结束会请求清理运行环境 退出与清理结果以执行回执为准</p>
        <p v-if="probeResult" role="status">{{ probeResult }}</p>
        <a :href="state.sourceUrl" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">查看魔搭服务详情</a>
      </article>
      <section v-if="state.lifecycle?.supported" class="execution-panel" aria-labelledby="mcp-versions-heading">
        <div class="execution-heading"><h3 id="mcp-versions-heading"><el-icon><Collection /></el-icon>版本与存储</h3><el-tag>仅使用已批准发布包</el-tag></div>
        <dl class="storage-metrics"><div><dt>实际文件</dt><dd>{{ bytesLabel(state.lifecycle.storedBytes) }}</dd></div><div><dt>计入额度</dt><dd>{{ bytesLabel(state.lifecycle.chargedBytes) }} / {{ bytesLabel(state.lifecycle.quotaBytes) }}</dd></div><div><dt>待核对预留</dt><dd>{{ bytesLabel(state.lifecycle.reservedBytes) }}</dd></div></dl>
        <p>未确认安装退出时保留安装额度 清理保留历史审计及共享镜像中的许可证</p>
        <p v-if="state.transport==='STDIO'">本地安装分别核对 Java 写入阶段与安装子进程 连接检查也须确认退出 未核实前不能启用或清理</p>
        <p v-if="state.releaseCatalog?.image">目标运行镜像 <code>{{ state.releaseCatalog.image }}</code></p>
        <el-empty v-if="!state.lifecycle.items?.length" description="尚无版本快照 升级前会保存当前版本" />
        <TransitionGroup name="execution" tag="div" class="execution-list">
          <article v-for="item in state.lifecycle.items || []" :key="item.installationId" class="execution-card">
            <div class="execution-heading"><strong>Fetch {{ item.packageVersion||'版本未记录' }}</strong><div class="mcp-version-state"><span v-if="item.current===true" class="mcp-version-pointer">当前登记</span><span v-else-if="item.retainedForRollback===true" class="mcp-version-pointer">回退保留</span><StatusBadge domain="mcpVersion" :code="item.state" /></div></div>
            <p>安装编号 {{ item.installationId }} · {{ item.transport }}</p><p v-if="item.imageId">运行镜像 <code>{{ item.imageId }}</code></p>
            <p v-if="!item.writerExitVerified&&item.state!=='REMOVED'">安装执行退出尚未核实 文件继续保留</p>
            <p v-if="item.writerEvidenceCode" role="status">{{ writerEvidenceLabel(item.writerEvidenceCode) }}</p>
            <div class="execution-footer"><time>{{ beijingDateTime(item.updatedAt) }} UTC+8</time><div class="actions">
              <el-button v-if="state.lifecycle.writerReconciliationSupported&&!item.writerExitVerified&&['NEEDS_REVIEW','READY'].includes(item.state)" :disabled="busy" @click="versionAction(item,'reconcile-writer')">核对安装执行退出</el-button>
              <el-button v-if="item.retainedForRollback&&!item.current&&item.state==='READY'" :disabled="busy||state.status==='INSTALLING'" @click="versionAction(item,'rollback')">回退到此版本</el-button>
              <el-button v-if="item.retainedForRollback&&!item.current" :disabled="busy||state.status==='INSTALLING'" @click="versionAction(item,'release-retention')">不再保留回退</el-button>
              <el-button v-if="canClean(item)" :disabled="busy" @click="versionAction(item,'cleanup')">清理无引用文件</el-button>
            </div></div>
          </article>
        </TransitionGroup>
      </section>
      <section v-if="state.executionReceipts?.supported" class="execution-panel" aria-labelledby="mcp-exit-heading">
        <div class="execution-heading"><h3 id="mcp-exit-heading"><el-icon><ShieldCheck /></el-icon>执行与退出回执</h3><span class="mcp-pending-count" :data-pending="knownCount(state.executionReceipts.pendingCount)>0"><AppIcon :name="knownCount(state.executionReceipts.pendingCount)>0?'Clock':'Document'" :size="14" />{{ knownCount(state.executionReceipts.pendingCount)==null?'占用数量尚未核对':knownCount(state.executionReceipts.pendingCount)>0?`${knownCount(state.executionReceipts.pendingCount)} 项仍占用执行额度`:'当前记录无待核对占用' }}</span></div>
        <p>退出与执行资源清理分别记录 刷新只读取状态 不会重新抓取网页 服务重启后仍可核对</p>
        <CollectionEmptyState v-if="!Array.isArray(state.executionReceipts.items)||!state.executionReceipts.items.length" :empty-title="Array.isArray(state.executionReceipts.items)?'尚无已登记的执行回执':'执行回执列表尚未核对'" empty-description="只查看当前账号已返回的记录，不根据空列表推断文件或进程已经清理。" />
        <TransitionGroup name="execution" tag="div" class="execution-list">
          <article v-for="item in state.executionReceipts.items || []" :key="item.executionId" class="execution-card" :class="{'needs-review':item.state==='NEEDS_REVIEW'}">
            <div class="execution-heading"><strong>{{ item.purpose==='INSTALL_PROBE'?'安装连接检查':item.purpose==='PROBE'?'连接检查':['CALL','FETCH'].includes(item.purpose)?'网页抓取':'已登记执行' }}</strong><StatusBadge domain="mcpExecution" :code="item.state" /></div>
            <p class="execution-id">执行编号 {{ item.executionId }} · {{ item.transport || state.executionReceipts.transport }}</p>
            <div class="execution-evidence"><span :class="{'confirmed':item.exitVerified===true}"><el-icon><CircleCheck v-if="item.exitVerified===true"/><Clock v-else/></el-icon>{{ item.exitVerified===true?'已确认退出':item.exitVerified===false?'退出尚未确认':'退出证明未记录' }}</span><span :class="{'confirmed':item.cleanupConfirmed===true}"><el-icon><CircleCheck v-if="item.cleanupConfirmed===true"/><Clock v-else/></el-icon>{{ item.cleanupConfirmed===true?'已确认清理':item.cleanupConfirmed===false?'清理尚未确认':'清理回执未记录' }}</span></div>
            <div class="execution-footer"><time>{{ beijingDateTime(item.updatedAt) }} UTC+8</time><el-button v-if="!item.cleanupConfirmed" :disabled="busy" @click="reconcile(item)">{{ ['OPENING','RUNNING'].includes(item.state)?'终止并核对':'核对退出与清理' }}</el-button></div>
          </article>
        </TransitionGroup>
      </section>
      <p v-else-if="state.transport==='STDIO'">当前 Stdio 未启用持久退出证明 关闭连接不代表已核实进程退出</p>
      <details v-if="state.manifest" class="files-panel mcp-manifest"><summary><AppIcon name="Files" :size="17" />运行文件清单与许可证</summary><p>包摘要 {{ state.manifest.packageSha256||'未记录' }}</p><el-table :scrollbar-tabindex="0" role="region" aria-label="固定 Fetch 运行文件清单" :data="Array.isArray(state.manifest.artifacts)?state.manifest.artifacts:[]"><el-table-column prop="name" label="依赖" min-width="160"/><el-table-column prop="version" label="固定版本" min-width="130"/><el-table-column prop="path" label="包内相对路径" min-width="230"/></el-table><p>许可证/版权文件 {{ Array.isArray(state.manifest.licenses)?state.manifest.licenses.length:'数量未核对' }} · 依赖摘要保存在安装清单，网关模式的依赖包与许可证保留在固定运行镜像内。</p></details>
      <section class="audit-panel"><h3>本人操作审计</h3><el-empty v-if="!state.audit?.length" description="暂无 MCP 操作"/><p v-for="(event,index) in state.audit || []" :key="index">{{ event.action_name }} · {{ event.outcome }} · {{ beijingDateTime(event.created_at) }} UTC+8<router-link v-if="event.run_id" :to="{path:'/agent/trace',query:{runId:event.run_id}}">查看本人运行</router-link></p></section>
    </template>
    <SharedFetchImages v-if="state?.sharedImageManagementSupported===true" />
    <el-dialog v-model="installOpen" append-to-body class="local-mcp-dialog" title="确认安装 Fetch MCP" width="min(720px,94vw)" :close-on-click-modal="false" :show-close="!busy">
      <template v-if="state"><p>安装 mcp-server-fetch {{ state.version }}。网关模式登记已核对的隔离运行镜像，本地模式创建专属 Python 环境。两者都检查 MCP 握手，安装完成保持未启用。</p><p v-if="state.lifecycle?.supported&&state.status==='INSTALLED'">升级会停用当前工具并保存原版本 失败时恢复原登记 保持停用 等待本人核对</p><p>存储 {{ state.directory }}/installs/安装编号</p><p>此处仅安装已核对的固定 Fetch 包 不执行自定义命令</p><a href="https://pypi.org/project/mcp-server-fetch/2026.10.10/" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">核对版本与许可</a><el-checkbox v-model="licenseAccepted" :disabled="busy">我确认安装此固定版本并已核对 MIT 许可证</el-checkbox></template>
      <p v-if="dialogError" class="error" role="alert">{{ dialogError }}</p>
      <template #footer><el-button :disabled="busy" @click="installOpen=false"><AppIcon name="Close" :size="16" />取消</el-button><el-button type="primary" :disabled="!licenseAccepted" :loading="busy" @click="install">确认安装</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import AgentSectionIcon from "@/components/chat/AgentSectionIcon.vue"
import AgentLifecycleGuide from '@/components/chat/AgentLifecycleGuide.vue'
import SharedFetchImages from '@/components/SharedFetchImages.vue'
import { ref,onMounted,onBeforeUnmount } from 'vue'
import { Connection, CircleCheck, Clock, Collection, Lock as ShieldCheck } from '@element-plus/icons-vue'
import { beijingDateTime as renderBeijingTime } from '@/utils/beijingTime'
import {knownCount} from '@/utils/countPresentation'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import { ElMessageBox } from 'element-plus'
import request from '@/api/request'
const state=ref(null),loading=ref(false),busy=ref(false),error=ref(''),dialogError=ref(''),probeResult=ref(''),installOpen=ref(false),licenseAccepted=ref(false)
const headers={'X-MCP-Action':'update'}
const beijingDateTime=value=>value?renderBeijingTime(value)||'时间格式未知':'未记录'
const mcpStages=[{title:'本人确认来源',description:'核对固定版本、用途与许可证'},{title:'安装与连接核验',description:'保存登记并核对安装、连接回执'},{title:'本人主动启用',description:'安装完成后仍需单独启用'},{title:'执行与清理核对',description:'保留退出及清理证据，未知结果待核对'}]
let generation=0,timer=null,requestId=''
let mounted=true,cancelPromptOpen=false,removePromptOpen=false,reconcilePromptOpen=false,lifecyclePromptOpen=false
const statusLabel=value=>({NOT_INSTALLED:'未安装',PENDING_CONFIRM:'待本人确认',INSTALLING:'安装中',INSTALLED:'已安装',ERROR:'安装失败',CANCELLED:'已取消安装',UNINSTALLED:'已移除登记'}[value]||value)
const bytesLabel=value=>knownCount(value)==null?'未知':`${(knownCount(value)/1048576).toFixed(2)} MiB`
const canClean=item=>item.current===false&&item.retainedForRollback===false&&item.writerExitVerified===true&&['READY','CACHED','CLEANUP_REVIEW'].includes(item.state)
const nativeWriterEvidence={INSTALL_NEVER_DISPATCHED:'排队任务在领取前撤销 没有启动安装写入',NATIVE_INSTALL_TREE_STOPPED:'已核对 Java 写入结束与安装子进程树退出',NATIVE_INSTALLER_UNVERIFIED:'安装子进程退出仍待核对 继续保留文件和额度',INSTALL_PROBE_EXIT_UNVERIFIED:'安装写入已结束 连接检查进程仍待核对 请先处理执行回执'}
const writerEvidenceLabel=value=>nativeWriterEvidence[value]||({WRITER_RETURNED:'已确认安装写入结束',CONTROLLER_EXIT_CONFIRMED:'已确认原执行服务进程退出',CONTROLLER_GENERATION_REPLACED:'已确认原执行服务代次结束',CONTROLLER_CONTAINER_EXITED:'已确认原服务容器代次结束',NO_CONTROLLER_EVIDENCE:'历史安装没有写入者身份记录 无法独立证明退出',CONTROLLER_NAMESPACE_CHANGED:'执行节点已变化 尚无独立退出证明',CONTROLLER_STILL_ALIVE:'原服务仍在运行 暂不能独立证明安装写入已结束',CONTROLLER_CONTAINER_UNVERIFIED:'原服务容器退出尚未核实',CONTROLLER_PROOF_UNAVAILABLE:'退出证明暂不可用 已保留预留额度'}[value]||'安装退出结果仍需核对')
async function versionAction(item,action){
  if(busy.value)return
  const operation=item.installationId,expectedRevision=action==='rollback'?state.value.revision:item.revision,requestId=crypto.randomUUID()
  const options={rollback:['回退到此版本','恢复此版本的安装登记并保持停用。文件和发布许可会重新核对，后续需本人手动启用。'],'release-retention':['不再保留回退','解除此版本的回退保留。文件暂不删除，之后可单独清理；此版本将不能通过回退按钮恢复。'],cleanup:['清理无引用文件','删除此安装的无引用文件。当前版本、回退保留和退出未核实的目录不会删除，历史审计和共享镜像保留。'],'reconcile-writer':['核对安装执行退出','核对原安装写入者是否已经结束，不会重新安装或启用工具。不能取得独立退出证明时继续保留文件和预留额度。']}[action]
  if(!options)return
  busy.value=true;error.value='';clearTimeout(timer);generation++;loading.value=false;lifecyclePromptOpen=true
  try{
    await ElMessageBox.confirm(options[1],options[0],{confirmButtonText:options[0],cancelButtonText:'保留当前状态',closeOnClickModal:false})
    lifecyclePromptOpen=false;if(!mounted)return
    const path=action==='cleanup'?`storage/${encodeURIComponent(operation)}/cleanup`:`versions/${encodeURIComponent(operation)}/${action}`
    await request.post(`/api/agent/mcp/fetch/${path}`,{expectedRevision,requestId,confirmed:true},{headers,timeout:45000})
    if(mounted){probeResult.value='';await refresh()}
  }catch(e){if(mounted&&e!=='cancel'&&e!=='close'){await refresh();error.value=e.response?.data?.message||'操作结果尚未核实 请查看最新状态 不会自动重试'}}
  finally{lifecyclePromptOpen=false;if(mounted)busy.value=false}
}
async function refresh(){if(!mounted)return;const n=++generation;loading.value=true;error.value='';clearTimeout(timer);try{const result=await request.get('/api/agent/mcp/fetch');if(n!==generation)return;const value=result.data;if(!value||typeof value.name!=='string'||typeof value.status!=='string'||!Number.isSafeInteger(value.revision)||value.revision<0)throw Error('MCP 状态响应不完整');state.value=value;if(state.value.status==='INSTALLING')timer=setTimeout(refresh,4000)}catch(e){if(n===generation){state.value=null;error.value=e.response?.data?.message||'本地 MCP 状态暂不可核对，请核对服务与前后端版本'}}finally{if(n===generation)loading.value=false}}
function openInstall(){licenseAccepted.value=false;dialogError.value='';requestId=crypto.randomUUID();installOpen.value=true}
async function install(){if(busy.value)return;busy.value=true;dialogError.value='';try{state.value=(await request.post('/api/agent/mcp/fetch/install',{expectedRevision:state.value.revision,requestId,licenseAccepted:licenseAccepted.value},{headers})).data;installOpen.value=false;await refresh()}catch(e){dialogError.value=e.response?.data?.message||'安装结果尚未核实 请刷新状态后核对'}finally{busy.value=false}}
async function probe(){busy.value=true;probeResult.value='';try{const result=await request.post('/api/agent/mcp/fetch/probe',null,{headers,timeout:30000});probeResult.value=result.data.connected?'MCP 握手成功 已发现 fetch 工具':'连接未完成';await refresh()}catch(e){error.value=e.response?.data?.message||'MCP 连接失败'}finally{busy.value=false}}
async function reconcile(item){
  if(busy.value||item.cleanupConfirmed)return
  const executionId=item.executionId,expectedRevision=item.revision,requestId=crypto.randomUUID()
  busy.value=true;error.value='';clearTimeout(timer);generation++;loading.value=false;reconcilePromptOpen=true
  try{
    await ElMessageBox.confirm('终止并核对选中的执行。只查询退出及清理回执，不会重新抓取网页；无法确认时继续保留占用。','核对执行状态',{confirmButtonText:'终止并核对',cancelButtonText:'保留当前状态',closeOnClickModal:false})
    reconcilePromptOpen=false;if(!mounted)return
    await request.post(`/api/agent/mcp/fetch/executions/${encodeURIComponent(executionId)}/reconcile`,{expectedRevision,requestId,confirmed:true},{headers,timeout:45000})
    if(mounted)await refresh()
  }catch(e){if(mounted&&e!=='cancel'&&e!=='close'){await refresh();error.value=e.response?.data?.message||'退出结果尚未核实 请查看最新回执 不会自动重试'}}
  finally{reconcilePromptOpen=false;if(mounted)busy.value=false}
}
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
onMounted(refresh);onBeforeUnmount(()=>{mounted=false;generation++;clearTimeout(timer);if(cancelPromptOpen||removePromptOpen||reconcilePromptOpen||lifecyclePromptOpen)ElMessageBox.close()})
</script>
<style scoped>
.mcp-page{padding:24px;border-radius:16px;background:#fff;border:1px solid #e3eaf5}.mcp-page header,.server-title,.actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.mcp-page header{justify-content:space-between}.server-card,.files-panel,.audit-panel{margin:20px 0;padding:20px;background:#f7faff;border:1px solid #dce7f7;border-radius:12px}.mcp-page p{font-size:13px;line-height:1.8;color:#64748b;overflow-wrap:anywhere}.mcp-page a{color:#2563eb;margin-left:8px}.server-title>.el-icon{font-size:24px;color:#2563eb}.error{color:#b42318!important}.mcp-page :deep(button){transition:transform .15s ease}.mcp-page :deep(button:hover:not(:disabled)){transform:scale(1.02)}@media(prefers-reduced-motion:reduce){.mcp-page :deep(button){transition:none;transform:none!important}}@media(max-width:600px){.mcp-page{padding:12px}.server-card,.files-panel,.audit-panel{padding:12px}}
.execution-panel{margin:20px 0;padding:20px;border:1px solid #dce7f7;border-radius:14px;background:linear-gradient(135deg,#f3f7ff,#fff)}.execution-heading,.execution-footer,.execution-evidence{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.execution-heading h3{display:flex;align-items:center;gap:8px}.execution-heading h3 .el-icon{color:#2563eb}.execution-list{display:grid;gap:12px}.execution-card{padding:16px;border:1px solid #dfe7f2;border-radius:12px;background:#fff}.execution-card.needs-review{border-color:#f3d28b;background:#fffdf7}.execution-evidence{justify-content:flex-start;font-size:13px;color:#94621a}.execution-evidence span{display:inline-flex;align-items:center;gap:5px}.execution-evidence .confirmed{color:#13795b}.execution-footer{margin-top:12px}.execution-footer time{font-size:12px;color:#64748b}.execution-enter-active,.execution-leave-active,.execution-move{transition:opacity .18s ease,transform .18s ease}.execution-enter-from,.execution-leave-to{opacity:0;transform:translateY(6px)}@media(prefers-reduced-motion:reduce){.execution-enter-active,.execution-leave-active,.execution-move{transition:none}}@media(max-width:600px){.execution-panel{padding:12px}.execution-card{padding:12px}.execution-footer{align-items:flex-start}}
.storage-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0}.storage-metrics>div{padding:14px;border:1px solid #dce7f7;border-radius:10px;background:#fff}.storage-metrics dt{color:#64748b;font-size:12px}.storage-metrics dd{margin:8px 0 0;color:#1d4ed8;font-weight:600;font-size:14px;overflow-wrap:anywhere}.execution-heading .el-tag+.el-tag{margin-left:6px}@media(max-width:700px){.storage-metrics{grid-template-columns:1fr}}
</style>
<style>
.local-mcp-dialog .el-dialog__body{max-height:65vh;overflow:auto}.local-mcp-dialog p{font-size:13px;line-height:1.8;overflow-wrap:anywhere}.local-mcp-dialog .el-checkbox{margin-top:18px;height:auto}.local-mcp-dialog .el-checkbox__label{white-space:normal;line-height:1.8}.local-mcp-dialog .error{color:#b42318}
</style>
