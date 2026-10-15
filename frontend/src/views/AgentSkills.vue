<template>
  <section class="skills-page app-panel">
    <header><div><h2>Agent 技能演化</h2><p>授权经验来源 创建技能草稿 规则评测 独立审核与版本回退</p></div><el-button :loading="loading" @click="refresh">刷新</el-button></header>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <el-alert title="自动 Eval 检查结构与权限规则 业务适用性和隐私仍需主管人工审核" type="info" :closable="false" />
    <section class="source-panel link-install-panel">
      <h3>从链接安装 Skill</h3>
      <p v-if="storageStatus">本人存储 {{ mib(storageStatus.usedBytes) }} / {{ mib(storageStatus.quotaBytes) }} MiB · 文件 {{ storageStatus.files }} · 下载预留 {{ mib(storageStatus.reservedBytes) }} MiB</p>
      <p>输入公开 GitHub 的 Skill 目录链接 下载到本人后端存储 再评测并提交独立审核</p>
      <el-input v-model="linkUrl" aria-label="Skill 来源链接" placeholder="https://github.com/组织/仓库/tree/main/skills/技能名" maxlength="1000" />
      <el-select v-model="linkRole" aria-label="链接技能目标角色"><el-option label="员工" value="INSPECTOR" /><el-option v-if="supervisor" label="主管" value="SUPERVISOR" /></el-select>
      <el-button type="primary" :disabled="busy || !linkUrl.trim() || !linksEnabled" :loading="linkBusy" @click="installLink">确认下载为私人草稿</el-button>
      <p>魔搭目前支持 anthropics/skill-creator 的已核对来源映射 脚本和附件只存档 不执行或自动启用</p>
      <p v-if="linkError" class="error" role="alert">{{ linkError }}</p>
      <el-table v-if="downloads.length" :data="downloads" row-key="download_id">
        <el-table-column label="来源" min-width="200"><template #default="{ row }"><span class="download-source">{{ row.source_url }}</span></template></el-table-column>
        <el-table-column label="下载状态" width="145"><template #default="{ row }">{{ downloadLabel(row.status) }}</template></el-table-column>
        <el-table-column label="操作" width="120"><template #default="{ row }"><el-button v-if="row.skill_id" text @click="select({skillId:row.skill_id})">查看私人草稿</el-button><el-button v-if="['ERROR','NO_CHANGE','CLEANUP_ERROR'].includes(row.status)" text :disabled="busy" @click="cleanupDownload(row)">清理下载缓存</el-button><span v-else-if="row.status==='PURGED'">已清理文件</span></template></el-table-column>
      </el-table>
      <details v-if="storageCommands.length"><summary>本人存储清理记录</summary><p v-for="command in storageCommands" :key="command.request_id">{{ command.download_id }} · {{ command.status }} · 已核实清理 {{ command.removed_files }} 文件 {{ mib(command.removed_bytes) }} MiB</p></details>
    </section>
    <section class="source-panel">
      <h3>本人经验来源</h3>
      <el-select v-model="sourceRunId" placeholder="选择本人已完成运行" aria-label="本人来源运行"><el-option v-for="run in runs" :key="run.runId" :value="run.runId" :label="run.startedAt + ' · ' + run.runId" /></el-select>
      <el-button :disabled="!sourceRunId || busy" @click="capture">授权提炼此运行</el-button>
      <p>仅保存成功工具名和完成时间 不复制聊天正文或业务参数 授权后可让助手按明确要求提议私人技能草稿</p>
      <el-button type="primary" :disabled="!sources.length || busy" @click="newDraft">编写技能草稿</el-button>
    </section>
    <el-table :data="skills" row-key="skillId" v-loading="loading">
      <el-table-column prop="name" label="技能" min-width="150" />
      <el-table-column label="目标角色" width="100"><template #default="{ row }">{{ roleLabel(row.targetRole) }}</template></el-table-column>
      <el-table-column label="状态" width="120"><template #default="{ row }">{{ stateLabel(row.versions[0]?.status) }}</template></el-table-column>
      <el-table-column label="发布版本" width="100"><template #default="{ row }">{{ row.versions.find(v=>v.version===row.activeVersion)?.evidence.sourceType === 'EXTERNAL_UPLOAD' ? '历史记录' : row.activeVersion ? 'v' + row.activeVersion : '未发布' }}</template></el-table-column>
      <el-table-column prop="useCount" label="实际加载" width="100" />
      <el-table-column label="维护" width="100"><template #default="{ row }">{{ row.lifecycle === 'ARCHIVED' ? '已停用' : !row.activeVersion ? '未启用' : row.lifecycle === 'STALE' ? '待维护' : '在用' }}</template></el-table-column>
      <el-table-column label="操作" width="120"><template #default="{ row }"><el-button text @click="select(row)">查看与管理</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="editing" class="learned-skill-dialog" append-to-body :title="editingSkill ? '修订技能版本' : '创建私人技能草稿'" width="min(720px, 94vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="名称 小写字母数字和短横线"><el-input v-model="form.name" :disabled="!!editingSkill" maxlength="64" /></el-form-item>
        <el-form-item label="目标角色"><el-select v-model="form.targetRole" :disabled="!!editingSkill" @change="form.tools=[]"><el-option label="员工" value="INSPECTOR" /><el-option v-if="supervisor" label="主管" value="SUPERVISOR" /></el-select></el-form-item>
        <el-form-item label="适用场景"><el-input v-model="form.description" maxlength="300" /></el-form-item>
        <el-form-item label="脱敏经验步骤 40 到 6000 字符"><el-input v-model="form.instructions" type="textarea" :rows="7" maxlength="6000" /></el-form-item>
        <el-form-item label="已授权来源"><el-select v-model="form.sourceRunId" @change="sourceChanged"><el-option v-for="source in sources" :key="source.run_id" :label="source.run_id" :value="source.run_id" /></el-select></el-form-item><el-form-item label="来源运行已成功的工具"><el-select v-model="form.tools" multiple><el-option v-for="tool in sourceTools" :key="tool" :value="tool" :label="tool" /></el-select></el-form-item>
      </el-form>
      <p v-if="dialogError" class="error" role="alert">{{ dialogError }}</p>
      <template #footer><el-button @click="editing=false">取消</el-button><el-button type="primary" :loading="busy" @click="saveDraft">保存私人草稿</el-button></template>
    </el-dialog>
    <el-dialog v-model="detailOpen" class="learned-skill-dialog" append-to-body title="技能详情与审核" width="min(880px, 96vw)" :close-on-click-modal="false">
      <template v-if="selected">
        <h3>{{ selected.name }} · {{ roleLabel(selected.targetRole) }}</h3>
        <p>修订号 {{ selected.revision }} · 当前发布 {{ selected.versions.find(v=>v.version===selected.activeVersion)?.evidence.sourceType === 'EXTERNAL_UPLOAD' ? '历史记录 已停止加载' : selected.activeVersion ? 'v' + selected.activeVersion : '无' }} · 实际加载 {{ selected.useCount }}</p>
        <el-alert v-if="latest?.evidence.sourceType === 'LINK'" title="当前仅审核与读取正文 脚本和附件不执行 不授予额外工具权限" type="info" :closable="false" />
        <el-alert v-if="externalLatest" title="外部上传功能已移除 此记录仅供历史查看或停用" type="info" :closable="false" />
        <article v-for="version in selected.versions" :key="version.version" class="version-card">
          <strong>v{{ version.version }} {{ stateLabel(version.status) }}</strong><p>{{ version.description }}</p>
          <p v-if="version.evidence.sourceType === 'LINK'">下载来源 {{ version.evidence.sourceUrl }} · 固定提交 {{ version.evidence.commit }}</p>
          <pre class="skill-body-preview">{{ version.instructions }}</pre><p>工具 {{ version.tools.length ? version.tools.join(' · ') : '正文参考 不新增工具' }}</p>
          <section v-if="['EXTERNAL_UPLOAD','LINK'].includes(version.evidence.sourceType)"><strong>外部导入来源</strong><p>{{ version.evidence.sourceUrl }} · 版本 {{ version.evidence.sourceVersion }}</p><p>固定提交 {{ version.evidence.commit || version.evidence.sourceVersion }} · 清单摘要 {{ version.evidence.manifestSha256 || version.evidence.packageSha256 }}</p><p>{{ version.evidence.sourceType === 'LINK' ? '已核验固定提交与本地文件摘要 脚本和资源只存档 不执行 不扩展工具权限' : '历史上传来源声明 未验证远端一致性' }}</p><details v-for="(text,path) in version.evidence.licenses" :key="path"><summary>{{ path }} · 许可证与版权原文</summary><pre>{{ text }}</pre></details></section>
          <p v-else>来源成功工具 {{ version.evidence.tools?.join(' · ') }} · 完成 {{ version.evidence.completedAt }}</p>
          <router-link v-if="version.sourceRunId" :to="{ path: '/agent/trace', query: { runId: version.sourceRunId } }">查看本人来源轨迹</router-link>
          <p v-if="version.reviewReason">审核意见 {{ version.reviewReason }}</p>
        </article>
        <el-button v-if="owned && latest?.evidence.sourceType === 'LINK' && selected.lifecycle !== 'ARCHIVED'" type="danger" :disabled="busy" @click="uninstallLink">卸载此链接技能</el-button>
        <section v-if="latest?.evidence.sourceType === 'LINK'" class="version-tools">
          <el-button v-if="owned" :disabled="busy || !linksEnabled || latest.status === 'SUBMITTED'" @click="openUpgrade">下载原技能的新版本</el-button>
          <template v-if="selected.versions.length > 1">
            <el-select v-model="compareFrom" aria-label="比较旧版本"><el-option v-for="v in selected.versions" :key="v.version" :label="'旧版本 v'+v.version" :value="v.version" /></el-select>
            <el-select v-model="compareTo" aria-label="比较新版本"><el-option v-for="v in selected.versions" :key="v.version" :label="'新版本 v'+v.version" :value="v.version" /></el-select>
            <el-button :disabled="busy || compareFrom === compareTo" @click="compareVersions">查看版本差异</el-button>
          </template>
        </section>
        <h4>规则 Eval</h4><p v-if="!selected.evaluations.length">尚未评测</p>
        <article v-for="(evaluation, index) in selected.evaluations" :key="index" class="eval-row"><strong>v{{ evaluation.version_no }} {{ evaluation.result.passed ? '规则通过' : '规则未通过' }}</strong><p v-for="(passed, rule) in evaluation.result.checks" :key="rule">{{ rule }} · {{ passed ? '通过' : '未通过' }}</p></article>
        <h4>操作审计</h4><p v-for="(event, index) in selected.audit" :key="index" class="audit-row">v{{ event.version_no }} · {{ event.action_name }} · {{ event.reason }} · {{ event.created_at }}</p>
        <div v-if="owned && !externalLatest" class="actions">
          <el-button v-if="['DRAFT','EVALUATED'].includes(latest?.status)" :disabled="busy" @click="perform('eval')">运行规则 Eval</el-button>
          <el-button v-if="latest?.status === 'EVALUATED'" type="primary" :disabled="busy" @click="perform('submit')">提交独立审核</el-button>
          <el-button v-if="latest?.status !== 'SUBMITTED' && latest?.evidence.sourceType !== 'LINK'" :disabled="busy" @click="revise">修订新版本</el-button>
        </div>
        <section v-if="supervisor && !owned && !externalLatest && latest?.status === 'SUBMITTED'" class="review-panel">
          <el-checkbox v-model="businessReviewed">已核对经验的业务适用性</el-checkbox><el-checkbox v-model="privacyReviewed">已核对内容脱敏及角色权限</el-checkbox>
          <el-input v-model="reason" type="textarea" placeholder="审核意见" maxlength="500" />
          <el-button type="primary" :disabled="busy || !businessReviewed || !privacyReviewed || !reason.trim()" @click="decision('APPROVE')">审核并发布</el-button>
          <el-button :disabled="busy || !businessReviewed || !privacyReviewed || !reason.trim()" @click="decision('REJECT')">驳回</el-button>
        </section>
        <section v-if="supervisor && (externalLatest || selected.versions.some(v => v.status === 'APPROVED'))" class="review-panel">
          <el-input v-model="reason" placeholder="停用或版本回退原因" maxlength="500" />
          <el-select v-if="!externalLatest" v-model="targetVersion" placeholder="选择已审核版本"><el-option v-for="v in selected.versions.filter(v=>v.status==='APPROVED' && v.evidence.sourceType !== 'EXTERNAL_UPLOAD')" :key="v.version" :value="v.version" :label="'v' + v.version" /></el-select>
          <el-button v-if="!externalLatest" :disabled="busy || !targetVersion || !reason.trim()" @click="rollback">切换到此审核版本</el-button><el-button type="danger" :disabled="busy || !reason.trim()" @click="archive">停用技能</el-button>
        </section>
      </template>
      <p v-if="dialogError" class="error" role="alert">{{ dialogError }}</p>
    </el-dialog>
    <el-dialog v-model="upgradeOpen" class="learned-skill-dialog" append-to-body title="下载原技能的新版本" width="min(680px,94vw)" :close-on-click-modal="false">
      <p>新包必须来自原仓库的同一技能目录 可以更换分支或固定提交 新版本仍需评测和独立审核 现有发布版本继续使用</p>
      <el-input v-model="upgradeUrl" aria-label="技能升级来源链接" placeholder="原技能目录的分支或固定提交链接" maxlength="1000" />
      <p v-if="upgradeError" role="alert" class="error">{{ upgradeError }}</p>
      <template #footer><el-button @click="upgradeOpen=false">取消</el-button><el-button type="primary" :loading="upgradeBusy" :disabled="!upgradeUrl.trim()" @click="startUpgrade">确认下载新版本</el-button></template>
    </el-dialog>
    <el-dialog v-model="comparisonOpen" class="learned-skill-dialog" append-to-body title="技能版本差异" width="min(1000px,96vw)">
      <template v-if="comparison">
        <p>v{{ comparison.fromVersion }} → v{{ comparison.toVersion }} · 固定提交 {{ comparison.fromCommit }} → {{ comparison.toCommit }}</p>
        <p>新增文件 {{ comparison.addedFiles.length }} · 删除文件 {{ comparison.removedFiles.length }} · 修改文件 {{ comparison.changedFiles.length }}</p>
        <p v-for="path in comparison.addedFiles" :key="'a'+path">新增 {{ path }}</p><p v-for="path in comparison.removedFiles" :key="'r'+path">删除 {{ path }}</p><p v-for="path in comparison.changedFiles" :key="'c'+path">修改 {{ path }}</p>
        <p>适用场景 {{ comparison.descriptionChanged ? '已变化' : '未变化' }} · 正文 {{ comparison.contentChanged ? '已变化' : '未变化' }}</p>
        <template v-if="comparison.mode === 'LINE_DIFF'"><p>正文新增 {{ comparison.addedLines }} 行 · 删除 {{ comparison.removedLines }} 行</p><pre class="comparison-lines"><span v-for="(line,index) in comparison.lines" :key="index" :class="line.type==='ADD'?'line-added':'line-removed'">{{ line.type==='ADD'?'+':'−' }} {{ line.newLine||line.oldLine }} {{ line.text }}
</span></pre></template>
        <p v-if="comparison.truncated">变化预览有长度限制 请结合下方完整正文核对 逐行比较超出计算限额时仅提供并排正文</p>
        <div class="comparison-grid"><section><h4>旧正文 v{{ compareFrom }}</h4><pre class="skill-body-preview">{{ comparedBefore }}</pre></section><section><h4>新正文 v{{ compareTo }}</h4><pre class="skill-body-preview">{{ comparedAfter }}</pre></section></div>
      </template><p v-if="comparisonError" role="alert" class="error">{{ comparisonError }}</p>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import request from '@/api/request'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
const skills=ref([]), sources=ref([]), runs=ref([]), mine=ref(null), selected=ref(null), loading=ref(false), busy=ref(false), error=ref(''), dialogError=ref('')
const sourceRunId=ref(''), sourceTools=ref([]), editing=ref(false), detailOpen=ref(false), editingSkill=ref(null), reason=ref(''), targetVersion=ref(null), businessReviewed=ref(false), privacyReviewed=ref(false)
const form=ref({}), supervisor=computed(()=>mine.value?.role==='SUPERVISOR'), owned=computed(()=>selected.value?.ownerUserId===mine.value?.userId), latest=computed(()=>selected.value?.versions.find(v=>v.version===selected.value.latestVersion))
const externalLatest=computed(()=>latest.value?.evidence.sourceType==='EXTERNAL_UPLOAD')
const route=useRoute()
const storageStatus=ref(null), storageCommands=ref([])
const downloads=ref([]), linkUrl=ref(typeof route.query.installUrl==='string'?route.query.installUrl:''), linkRole=ref('INSPECTOR'), linkBusy=ref(false), linkError=ref(''), linksEnabled=ref(false)
const headers={'X-Skill-Action':'update'}
const upgradeOpen=ref(false), upgradeUrl=ref(''), upgradeBusy=ref(false), upgradeError=ref(''), compareFrom=ref(null), compareTo=ref(null), comparisonOpen=ref(false), comparison=ref(null), comparisonError=ref('')
const comparedBefore=computed(()=>selected.value?.versions.find(v=>v.version===compareFrom.value)?.instructions||''), comparedAfter=computed(()=>selected.value?.versions.find(v=>v.version===compareTo.value)?.instructions||'')
let upgradeRequestId='', upgradeRevision=0, upgradeSkillId=''
let downloadTimer=null, downloadGeneration=0, stopped=false
let generation=0, requestId=''
const roleLabel=role=>role==='SUPERVISOR'?'主管':'员工'
const stateLabel=status=>({DRAFT:'私人草稿',EVALUATED:'规则通过',SUBMITTED:'待主管审核',APPROVED:'已审核',REJECTED:'已驳回'}[status]||'无可见版本')
async function refresh(){const n=++generation;loading.value=true;error.value='';try{const [identity,list,sourceList,history]=await Promise.all([request.get('/api/organization/me'),request.get('/api/agent/skills'),request.get('/api/agent/skills/sources'),request.get('/api/agent/runs',{params:{limit:50}})]);if(n!==generation)return;mine.value=identity.data.data;skills.value=list.data;sources.value=sourceList.data;runs.value=history.data.filter(run=>run.status==='COMPLETED')}catch(e){if(n===generation)error.value=e.response?.data?.message||'技能演化尚未启用或服务暂不可用'}finally{if(n===generation)loading.value=false}}
const downloadLabel=status=>({DOWNLOADING:'正在下载与核验',DRAFT_CREATED:'下载完成 已保存',ERROR:'下载失败 请核对来源',DOWNLOADED:'正在创建草稿',NO_CHANGE:'已核对 无版本变化',PURGING:'清理中 结果待核对',PURGED:'文件已清理',CLEANUP_ERROR:'清理未核实 请重试'}[status]||status)
async function refreshDownloads(){const n=++downloadGeneration;clearTimeout(downloadTimer);if(stopped)return;try{const [result,stats,audit]=await Promise.all([request.get('/api/agent/skills/links'),request.get('/api/agent/skills/links/storage'),request.get('/api/agent/skills/links/storage/audit')]);if(stopped||n!==downloadGeneration)return;downloads.value=result.data;storageStatus.value=stats.data;storageCommands.value=audit.data;linksEnabled.value=true;linkError.value='';if(downloads.value.some(d=>d.status==='DOWNLOADING')){clearTimeout(downloadTimer);downloadTimer=setTimeout(async()=>{await refreshDownloads();await refresh()},2500)}}catch(e){if(stopped||n!==downloadGeneration)return;downloads.value=[];storageStatus.value=null;storageCommands.value=[];linksEnabled.value=false;linkError.value=e.response?.data?.message||'链接安装未启用或服务暂不可用'}}
const mib=value=>(Number(value||0)/1048576).toFixed(2)
async function cleanupDownload(row){try{await ElMessageBox.confirm('清理本人未被任何技能版本引用的下载缓存 实际删除本地包文件 保留来源记录和清理审计 已审核及历史版本引用的包会拒绝清理','确认清理下载缓存',{confirmButtonText:'确认清理',cancelButtonText:'取消'});busy.value=true;const result=(await request.post('/api/agent/skills/links/downloads/'+row.download_id+'/cleanup',{requestId:crypto.randomUUID(),confirmed:true},{headers})).data;if(result.status!=='COMPLETED')throw new Error('清理结果尚未全部核实 请刷新存储和清理记录');await refreshDownloads()}catch(e){if(e!=='cancel'&&e!=='close')linkError.value=e.response?.data?.message||e.message||'清理结果未核实'}finally{busy.value=false}}
async function installLink(){try{await ElMessageBox.confirm('将从此公开链接下载固定版本到本人后端存储 不运行脚本 不自动启用 下载完成后需规则 Eval 和另一名主管审核','确认链接下载',{confirmButtonText:'确认下载',cancelButtonText:'取消'});linkBusy.value=true;linkError.value='';await request.post('/api/agent/skills/links',{url:linkUrl.value.trim(),targetRole:linkRole.value,requestId:crypto.randomUUID(),confirmed:true},{headers});await refreshDownloads()}catch(e){if(e!=='cancel'&&e!=='close')linkError.value=e.response?.data?.message||'下载结果尚未核实 请刷新核对'}finally{linkBusy.value=false}}
function openUpgrade(){upgradeSkillId=selected.value.skillId;upgradeRevision=selected.value.revision;upgradeUrl.value=latest.value.evidence.sourceUrl;upgradeRequestId=crypto.randomUUID();upgradeError.value='';upgradeOpen.value=true}
async function startUpgrade(){upgradeBusy.value=true;upgradeError.value='';try{await request.post('/api/agent/skills/links/'+upgradeSkillId+'/upgrade',{url:upgradeUrl.value.trim(),expectedRevision:upgradeRevision,requestId:upgradeRequestId,confirmed:true},{headers});upgradeOpen.value=false;await refreshDownloads()}catch(e){upgradeError.value=e.response?.data?.message||'升级下载结果尚未核实 请刷新核对 若更换参数需重新打开升级窗口'}finally{upgradeBusy.value=false}}
async function compareVersions(){comparisonOpen.value=true;comparison.value=null;comparisonError.value='';try{comparison.value=(await request.get('/api/agent/skills/links/'+selected.value.skillId+'/compare',{params:{fromVersion:compareFrom.value,toVersion:compareTo.value}})).data}catch(e){comparisonError.value=e.response?.data?.message||'版本差异暂不可读取 请刷新核对权限和文件完整性'}}
async function uninstallLink(){try{await ElMessageBox.confirm('停止加载本人安装的此技能 保留下载包、许可证、版本及审核审计 之后恢复需再次明确审核版本切换','确认卸载链接技能',{confirmButtonText:'确认卸载',cancelButtonText:'取消'});busy.value=true;selected.value=(await request.post('/api/agent/skills/links/'+selected.value.skillId+'/uninstall',{expectedRevision:selected.value.revision,reason:'用户明确卸载本人链接技能'},{headers})).data;await refresh()}catch(e){if(e!=='cancel'&&e!=='close')dialogError.value=e.response?.data?.message||'卸载结果尚未核实 请刷新核对'}finally{busy.value=false}}
async function capture(){try{await ElMessageBox.confirm('同意从此运行保存成功工具名和完成时间供经验提炼 不保存聊天正文和业务参数','授权经验来源',{confirmButtonText:'明确授权',cancelButtonText:'取消'});busy.value=true;await request.post('/api/agent/skills/sources/'+encodeURIComponent(sourceRunId.value)+'/consent',null,{headers});await refresh()}catch(e){if(e!=='cancel'&&e!=='close')error.value=e.response?.data?.message||'来源授权失败'}finally{busy.value=false}}
function sourceChanged(){form.value.tools=[];sourceTools.value=sources.value.find(source=>source.run_id===form.value.sourceRunId)?.tools||[]}
function newDraft(){editingSkill.value=null;form.value={name:'',targetRole:'INSPECTOR',description:'',instructions:'',sourceRunId:sources.value[0]?.run_id||'',tools:[]};requestId=crypto.randomUUID();dialogError.value='';editing.value=true;sourceChanged()}
async function select(row){reason.value='';targetVersion.value=null;businessReviewed.value=false;privacyReviewed.value=false;dialogError.value='';detailOpen.value=true;selected.value=null;try{selected.value=(await request.get('/api/agent/skills/'+row.skillId)).data;compareTo.value=selected.value.versions[0]?.version;compareFrom.value=selected.value.versions[1]?.version||compareTo.value;comparison.value=null}catch(e){dialogError.value=e.response?.data?.message||'技能详情不可用'}}
async function revise(){editingSkill.value=selected.value;const v=latest.value;form.value={name:selected.value.name,targetRole:selected.value.targetRole,description:v.description,instructions:v.instructions,sourceRunId:v.sourceRunId,tools:[...v.tools]};requestId=crypto.randomUUID();dialogError.value='';editing.value=true;sourceTools.value=v.evidence.tools||[]}
async function saveDraft(){busy.value=true;dialogError.value='';try{const url=editingSkill.value?'/api/agent/skills/'+editingSkill.value.skillId+'/versions?expectedRevision='+editingSkill.value.revision:'/api/agent/skills';const r=await request.post(url,{...form.value,requestId},{headers});selected.value=r.data;editing.value=false;detailOpen.value=true;await refresh()}catch(e){dialogError.value=e.response?.data?.message||'保存结果尚未核实 请刷新后核对'}finally{busy.value=false}}
async function perform(action,extra={}){busy.value=true;dialogError.value='';try{selected.value=(await request.post('/api/agent/skills/'+selected.value.skillId+'/'+action,{expectedRevision:selected.value.revision,...extra},{headers})).data;await refresh()}catch(e){dialogError.value=e.response?.data?.message||'操作结果尚未核实 请刷新后核对'}finally{busy.value=false}}
async function decision(value){try{await ElMessageBox.confirm(value==='APPROVE'?'发布后该角色的助手可在下一轮读取此技能 请再次核对正文、规则评测及脱敏内容':'确认驳回此技能版本','确认审核决定',{confirmButtonText:value==='APPROVE'?'确认发布':'确认驳回',cancelButtonText:'取消'});await perform('decision',{decision:value,reason:reason.value,businessReviewed:businessReviewed.value,privacyReviewed:privacyReviewed.value})}catch{}}
async function rollback(){try{await ElMessageBox.confirm('确认切换到已审核 v'+targetVersion.value+' 后续技能读取将使用该版本','确认版本切换',{confirmButtonText:'确认切换',cancelButtonText:'取消'});await perform('rollback',{targetVersion:targetVersion.value,reason:reason.value})}catch{}}
async function archive(){try{await ElMessageBox.confirm('停用后助手不能继续加载此技能 保留全部版本与审计','确认停用',{confirmButtonText:'确认停用',cancelButtonText:'取消'});await perform('archive',{reason:reason.value})}catch{}}
onMounted(async()=>{await refresh();await refreshDownloads()});onBeforeUnmount(()=>{stopped=true;generation++;downloadGeneration++;clearTimeout(downloadTimer)})
</script>
<style scoped>
.download-source{overflow-wrap:anywhere}.link-install-panel>.el-input{margin-bottom:12px}.skills-page{padding:24px;background:white;border:1px solid #e3eaf5;border-radius:16px}.skills-page>header{display:flex;justify-content:space-between;align-items:center;gap:16px}.skills-page p{color:#64748b;font-size:13px;line-height:1.7}.source-panel,.version-card,.review-panel,.eval-row{margin:18px 0;padding:16px;background:#f7faff;border:1px solid #dce7f7;border-radius:12px}.source-panel .el-select{width:min(520px,100%);margin-right:12px}.version-card pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.8;color:#23344d}.actions,.review-panel{display:flex;gap:12px;flex-wrap:wrap}.review-panel .el-textarea,.review-panel .el-input{width:100%}.error{color:#b42318!important}.audit-row{overflow-wrap:anywhere}.skills-page :deep(.el-dialog__body){max-height:70vh;overflow:auto}.skills-page :deep(button){transition:transform .15s ease}.skills-page :deep(button:hover:not(:disabled)){transform:scale(1.02)}.skills-page :deep(button:active:not(:disabled)){transform:scale(.98)}@media(prefers-reduced-motion:reduce){.skills-page :deep(button){transition:none;transform:none!important}}@media(max-width:600px){.skills-page{padding:12px}.skills-page>header{align-items:flex-start}.source-panel .el-button{margin:10px 0}}
</style>
<style>
.learned-skill-dialog .el-dialog__body{max-height:65vh;overflow:auto;overscroll-behavior:contain}.learned-skill-dialog .version-card,.learned-skill-dialog .review-panel,.learned-skill-dialog .eval-row{margin:18px 0;padding:16px;background:#f7faff;border:1px solid #dce7f7;border-radius:12px}.learned-skill-dialog pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.8}.learned-skill-dialog p{line-height:1.7;font-size:13px;overflow-wrap:anywhere}.learned-skill-dialog .actions,.learned-skill-dialog .review-panel{display:flex;gap:12px;flex-wrap:wrap}.learned-skill-dialog .review-panel .el-textarea,.learned-skill-dialog .review-panel .el-input{width:100%}.learned-skill-dialog .error{color:#b42318}.learned-skill-dialog button{transition:transform .15s ease}.learned-skill-dialog button:hover:not(:disabled){transform:scale(1.02)}.learned-skill-dialog button:active:not(:disabled){transform:scale(.98)}@media(prefers-reduced-motion:reduce){.learned-skill-dialog button{transition:none;transform:none!important}}@media(max-width:600px){.learned-skill-dialog .el-dialog__body{padding:12px}.learned-skill-dialog .version-card{padding:12px}}
</style>

<style>
.learned-skill-dialog .skill-body-preview{max-height:280px;overflow:auto;overscroll-behavior:contain;padding:10px;border:1px solid #dce7f7;border-radius:8px;background:#fff}
</style>

<style>
.learned-skill-dialog .version-tools{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}.learned-skill-dialog .version-tools .el-select{width:160px}.learned-skill-dialog .comparison-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.learned-skill-dialog .comparison-grid>section{min-width:0}.learned-skill-dialog .comparison-lines{max-height:260px;overflow:auto}.learned-skill-dialog .line-added{color:#175cd3}.learned-skill-dialog .line-removed{color:#b42318}@media(max-width:600px){.learned-skill-dialog .comparison-grid{grid-template-columns:1fr}}
</style>
