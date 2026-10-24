<template>
  <section class="skills-page app-panel">
    <header><div><h2><AgentSectionIcon kind="skills" />Agent 技能演化</h2><p>授权经验来源 创建技能草稿 规则评测 独立审核与版本回退</p></div><el-button :loading="loading" @click="refresh"><AppIcon name="Refresh" :size="16" />刷新</el-button></header>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <el-alert title="自动 Eval 检查结构与权限规则 业务适用性和隐私仍需主管人工审核" type="info" :closable="false" />
    <AgentLifecycleGuide label="Skill 从私人草稿到发布的流程" :steps="skillStages" />
    <section class="source-panel link-install-panel">
      <h3><AgentSectionIcon kind="skills" small />从链接安装 Skill</h3>
      <dl v-if="storageStatus" class="skill-storage-metrics"><div><dt>本人存储</dt><dd>{{ mib(storageStatus.usedBytes) }} / {{ mib(storageStatus.quotaBytes) }} MiB</dd></div><div><dt>已登记文件</dt><dd>{{ storageStatus.files ?? '—' }}</dd></div><div><dt>下载预留</dt><dd>{{ mib(storageStatus.reservedBytes) }} MiB</dd></div></dl>
      <p>支持公开 GitHub 目录、skills.sh 技能详情和魔搭 Skill 链接 下载到本人后端存储 再评测并提交独立审核</p>
      <div class="skill-link-form"><label class="skill-link-source">来源链接<el-input v-model="linkUrl" aria-label="Skill 来源链接" placeholder="https://github.com/组织/仓库/tree/main/skills/技能名" maxlength="1000" /></label><label>目标角色<el-select v-model="linkRole" aria-label="链接技能目标角色"><el-option label="员工" value="INSPECTOR" /><el-option v-if="supervisor" label="主管" value="SUPERVISOR" /></el-select></label><el-button type="primary" :disabled="busy || !linkUrl.trim() || !linksEnabled" :loading="linkBusy" @click="installLink"><AppIcon name="Download" :size="16" />确认下载为私人草稿</el-button></div>
      <p v-if="!linksEnabled && !linkError" class="detail-note">链接安装状态尚未核对，读取成功后才能下载。</p>
      <p>Git 来源固定提交 魔搭原生归档保存内容快照 脚本和附件只存档 不执行或自动启用</p>
      <p v-if="linkError" class="error" role="alert">{{ linkError }}</p>
      <el-table :scrollbar-tabindex="0" role="region" aria-label="本人 Skill 下载记录" v-if="downloads.length" :data="downloads" row-key="download_id">
        <el-table-column label="来源" min-width="200"><template #default="{ row }"><span class="download-source">{{ row.source_url }}</span></template></el-table-column>
        <el-table-column label="下载状态" min-width="210"><template #default="{ row }"><StatusBadge domain="skillDownload" :code="row.status" :label="downloadLabel(row.status)" /><small v-if="row.error_code">{{ downloadError(row.error_code) }}</small></template></el-table-column>
        <el-table-column label="操作" width="120"><template #default="{ row }"><el-button v-if="row.skill_id" text @click="select({skillId:row.skill_id})">查看私人草稿</el-button><el-button v-if="['ERROR','NO_CHANGE','CLEANUP_ERROR'].includes(row.status)" text :disabled="busy" @click="cleanupDownload(row)">清理下载缓存</el-button><span v-else-if="row.status==='PURGED'">已清理文件</span></template></el-table-column>
      </el-table>
      <details v-if="storageCommands.length"><summary>本人存储清理记录</summary><p v-for="command in storageCommands" :key="command.request_id">{{ command.download_id }} · {{ command.status }} · 已核实清理 {{ command.removed_files }} 文件 {{ mib(command.removed_bytes) }} MiB</p></details>
    </section>
    <section class="source-panel">
      <h3><AgentSectionIcon kind="skills" small />本人经验来源</h3>
      <el-select v-model="sourceRunId" placeholder="选择本人已完成运行" aria-label="本人来源运行"><el-option v-for="run in runs" :key="run.runId" :value="run.runId" :label="skillTime(run.startedAt) + ' UTC+8 · ' + run.runId" /></el-select>
      <el-button :disabled="!sourceRunId || busy" @click="capture">授权提炼此运行</el-button>
      <p>仅保存成功工具名和完成时间 不复制聊天正文或业务参数 授权后可让助手按明确要求提议私人技能草稿</p>
      <el-button type="primary" :disabled="!sources.length || busy" @click="newDraft">编写技能草稿</el-button>
    </section>
    <el-table :scrollbar-tabindex="0" role="region" aria-label="可查看的技能记录" :data="skills" row-key="skillId" v-loading="loading">
      <template #empty><CollectionEmptyState :loading="loading" :error="error" empty-title="暂无可查看的技能" empty-description="可从链接下载私人草稿，或授权已有运行经验后编写；评测与审核仍需分别完成。" @retry="refresh" /></template>
      <el-table-column label="技能" min-width="180"><template #default="{row}"><div class="skill-list-name"><strong>{{ row.name||'技能名称未记录' }}</strong><small>最新可见版本 {{ latestVisibleVersion(row)?.version??'未记录' }}</small></div></template></el-table-column>
      <el-table-column label="目标角色" width="100"><template #default="{ row }">{{ roleLabel(row.targetRole) }}</template></el-table-column>
      <el-table-column label="最新版本状态" min-width="145"><template #default="{ row }"><StatusBadge domain="skillVersion" :code="latestVisibleVersion(row)?.status" :label="stateLabel(latestVisibleVersion(row)?.status)" /></template></el-table-column>
      <el-table-column label="发布版本" width="100"><template #default="{ row }">{{ activeVisibleVersion(row)?.evidence?.sourceType === 'EXTERNAL_UPLOAD' ? '历史记录' : row.activeVersion ? 'v' + row.activeVersion : '未发布' }}</template></el-table-column>
      <el-table-column label="实际加载" width="100"><template #default="{row}">{{ knownCount(row.useCount)??'—' }}</template></el-table-column>
      <el-table-column label="维护" min-width="140"><template #default="{ row }"><StatusBadge domain="skillMaintenance" :code="skillMaintenance(row).code" /></template></el-table-column>
      <el-table-column label="操作" width="150"><template #default="{ row }"><el-button text :disabled="busy" @click="select(row)"><AppIcon name="Search" :size="15" />查看与管理</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="editing" class="learned-skill-dialog" append-to-body :title="editingSkill ? '修订技能版本' : '创建私人技能草稿'" width="min(720px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy">
      <el-form label-position="top" :disabled="busy" @submit.prevent="saveDraft">
        <el-form-item label="名称 小写字母数字和短横线"><el-input v-model="form.name" :disabled="!!editingSkill" maxlength="64" /></el-form-item>
        <el-form-item label="目标角色"><el-select v-model="form.targetRole" :disabled="!!editingSkill" @change="form.tools=[]"><el-option label="员工" value="INSPECTOR" /><el-option v-if="supervisor" label="主管" value="SUPERVISOR" /></el-select></el-form-item>
        <el-form-item label="适用场景"><el-input v-model="form.description" maxlength="300" /></el-form-item>
        <el-form-item label="脱敏经验步骤 40 到 6000 字符"><el-input v-model="form.instructions" type="textarea" :rows="7" maxlength="6000" /></el-form-item>
        <el-form-item label="已授权来源"><el-select v-model="form.sourceRunId" @change="sourceChanged"><el-option v-for="source in sources" :key="source.run_id" :label="source.run_id" :value="source.run_id" /></el-select></el-form-item><el-form-item label="来源运行已成功的工具"><el-select v-model="form.tools" multiple><el-option v-for="tool in sourceTools" :key="tool" :value="tool" :label="tool" /></el-select></el-form-item>
      </el-form>
      <p v-if="dialogError" class="error" role="alert">{{ dialogError }}</p>
      <template #footer><el-button :disabled="busy" @click="editing=false"><AppIcon name="Close" :size="16" />取消</el-button><el-button type="primary" :loading="busy" @click="saveDraft">保存私人草稿</el-button></template>
    </el-dialog>
    <el-dialog v-model="detailOpen" class="learned-skill-dialog" append-to-body title="技能详情与审核" width="min(880px, 96vw)" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy">
      <template v-if="selected">
        <div class="skill-detail-heading"><span><AppIcon name="Collection" :size="24" /></span><div><h3>{{ selected.name }}</h3><p>{{ roleLabel(selected.targetRole) }} · 修订号 {{ selected.revision??'未记录' }} · 实际加载 {{ knownCount(selected.useCount)??'—' }}</p></div><StatusBadge domain="skillMaintenance" :code="skillMaintenance(selected).code" /></div>
        <p class="skill-published-context">当前发布 {{ activeVisibleVersion(selected)?.evidence?.sourceType === 'EXTERNAL_UPLOAD' ? '历史上传记录，已停止加载' : selected.activeVersion ? 'v' + selected.activeVersion : '无已发布版本' }}。最新草稿和当前发布版本分别记录，修订草稿不会直接替换在用版本。</p>
        <el-alert v-if="latest?.evidence.sourceType === 'LINK'" title="当前仅审核与读取正文 脚本和附件不执行 不授予额外工具权限" type="info" :closable="false" />
        <el-alert v-if="externalLatest" title="外部上传功能已移除 此记录仅供历史查看或停用" type="info" :closable="false" />
        <SkillVersionRecord v-for="version in selected.versions" :key="version.version" :version="version" :active="version.version===selected.activeVersion&&version.evidence?.sourceType!=='EXTERNAL_UPLOAD'" :latest="version.version===latest?.version" />
        <el-button v-if="owned && latest?.evidence.sourceType === 'LINK' && selected.lifecycle !== 'ARCHIVED'" type="danger" :disabled="busy" @click="uninstallLink">卸载此链接技能</el-button>
        <section v-if="latest?.evidence.sourceType === 'LINK'" class="version-tools">
          <el-button v-if="owned" :disabled="busy || !linksEnabled || latest.status === 'SUBMITTED'" @click="openUpgrade">下载原技能的新版本</el-button>
          <template v-if="selected.versions.length > 1">
            <el-select v-model="compareFrom" aria-label="比较旧版本"><el-option v-for="v in selected.versions" :key="v.version" :label="'旧版本 v'+v.version" :value="v.version" /></el-select>
            <el-select v-model="compareTo" aria-label="比较新版本"><el-option v-for="v in selected.versions" :key="v.version" :label="'新版本 v'+v.version" :value="v.version" /></el-select>
            <el-button :disabled="busy || compareFrom === compareTo" @click="compareVersions">查看版本差异</el-button>
          </template>
        </section>
        <h4 class="skill-detail-section-title"><AppIcon name="DocumentChecked" :size="17" />规则评测</h4><p class="skill-detail-note">规则通过仅表示这些检查项通过，业务适用性与隐私仍需独立人工审核。</p><p v-if="!selected.evaluations.length">尚无已登记的规则评测</p>
        <article v-for="(evaluation, index) in selected.evaluations" :key="index" class="skill-rule-record"><header><strong>版本 {{ evaluation.version_no??'未记录' }}</strong><StatusBadge domain="skillRule" :code="skillRuleState(evaluation.result?.passed)" /></header><details><summary>查看逐项规则</summary><ul><li v-for="(passed, rule) in evaluation.result?.checks||{}" :key="rule"><span :title="rule">{{ skillRuleLabel(rule) }}</span><StatusBadge domain="skillRule" :code="skillRuleState(passed)" /></li></ul></details></article>
        <details class="skill-audit-history"><summary><AppIcon name="DocumentCopy" :size="16" />操作审计（{{ selected.audit.length }} 条已读取）</summary><AgentOperationHistory :records="selected.audit" kind="skill" label="当前 Skill 可见版本的操作记录" scope-note="仅显示当前可见版本的动作记录；规则评测、独立审核和发布分别核对。私人运行入口仅在接口返回本人编号时提供。" /></details>
        <div v-if="owned && latest && !externalLatest" class="actions">
          <el-button v-if="['DRAFT','EVALUATED'].includes(latest?.status)" :disabled="busy" @click="perform('eval')">运行规则 Eval</el-button>
          <el-button v-if="latest?.status === 'EVALUATED'" type="primary" :disabled="busy" @click="perform('submit')">提交独立审核</el-button>
          <el-button v-if="latest?.status !== 'SUBMITTED' && latest?.evidence.sourceType !== 'LINK'" :disabled="busy" @click="revise">修订新版本</el-button>
        </div>
        <section v-if="supervisor && !owned && !externalLatest && latest?.status === 'SUBMITTED'" class="review-panel">
          <el-checkbox v-model="businessReviewed" :disabled="busy">已核对经验的业务适用性</el-checkbox><el-checkbox v-model="privacyReviewed" :disabled="busy">已核对内容脱敏及角色权限</el-checkbox>
          <el-input v-model="reason" :disabled="busy" type="textarea" aria-label="审核意见" placeholder="审核意见" maxlength="500" />
          <el-button type="primary" :disabled="busy || !businessReviewed || !privacyReviewed || !reason.trim()" @click="decision('APPROVE')">审核并发布</el-button>
          <el-button :disabled="busy || !businessReviewed || !privacyReviewed || !reason.trim()" @click="decision('REJECT')">驳回</el-button>
        </section>
        <section v-if="supervisor && (externalLatest || selected.versions.some(v => v.status === 'APPROVED'))" class="review-panel">
          <el-input v-model="reason" :disabled="busy" aria-label="停用或版本回退原因" placeholder="停用或版本回退原因" maxlength="500" />
          <el-select v-if="!externalLatest" v-model="targetVersion" :disabled="busy" aria-label="选择已审核版本" placeholder="选择已审核版本"><el-option v-for="v in selected.versions.filter(v=>v.status==='APPROVED' && v.evidence.sourceType !== 'EXTERNAL_UPLOAD')" :key="v.version" :value="v.version" :label="'v' + v.version" /></el-select>
          <el-button v-if="!externalLatest" :disabled="busy || !targetVersion || !reason.trim()" @click="rollback">切换到此审核版本</el-button><el-button type="danger" :disabled="busy || !reason.trim()" @click="archive">停用技能</el-button>
        </section>
      </template>
      <CollectionEmptyState v-if="!selected" :loading="detailLoading" :error="dialogError" empty-title="技能资料尚未读取" empty-description="核对版本、来源和角色后再操作。" @retry="select({skillId:selectedSkillId})" />
      <p v-else-if="dialogError" class="error" role="alert">{{ dialogError }}</p>
    </el-dialog>
    <el-dialog v-model="upgradeOpen" class="learned-skill-dialog" append-to-body title="下载原技能的新版本" width="min(680px,94vw)" :close-on-click-modal="false" :close-on-press-escape="!upgradeBusy" :show-close="!upgradeBusy">
      <p>新包必须来自原仓库的同一技能目录 可以更换分支或固定提交 新版本仍需评测和独立审核 现有发布版本继续使用</p>
      <el-input v-model="upgradeUrl" :disabled="upgradeBusy" aria-label="技能升级来源链接" placeholder="原技能目录的分支或固定提交链接" maxlength="1000" />
      <p v-if="upgradeError" role="alert" class="error">{{ upgradeError }}</p>
      <template #footer><el-button :disabled="upgradeBusy" @click="upgradeOpen=false"><AppIcon name="Close" :size="16" />取消</el-button><el-button type="primary" :loading="upgradeBusy" :disabled="!upgradeUrl.trim()" @click="startUpgrade">确认下载新版本</el-button></template>
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
import AgentSectionIcon from "@/components/chat/AgentSectionIcon.vue"
import AgentLifecycleGuide from '@/components/chat/AgentLifecycleGuide.vue'
import AgentOperationHistory from '@/components/chat/AgentOperationHistory.vue'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import SkillVersionRecord from '@/components/chat/SkillVersionRecord.vue'
import {skillTime,skillMaintenance,skillRuleState,skillRuleLabel,readSkillView} from '@/utils/skillPresentation'
import { knownCount } from '@/utils/countPresentation'
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import request from '@/api/request'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
const skills=ref([]), sources=ref([]), runs=ref([]), mine=ref(null), selected=ref(null), loading=ref(false), busy=ref(false), error=ref(''), dialogError=ref('')
const detailLoading=ref(false),selectedSkillId=ref('')
let detailGeneration=0
const sourceRunId=ref(''), sourceTools=ref([]), editing=ref(false), detailOpen=ref(false), editingSkill=ref(null), reason=ref(''), targetVersion=ref(null), businessReviewed=ref(false), privacyReviewed=ref(false)
const form=ref({}), supervisor=computed(()=>mine.value?.role==='SUPERVISOR'), owned=computed(()=>selected.value?.ownerUserId===mine.value?.userId), latest=computed(()=>selected.value?.versions.find(v=>v.version===selected.value.latestVersion))
const externalLatest=computed(()=>latest.value?.evidence?.sourceType==='EXTERNAL_UPLOAD')
const latestVisibleVersion=row=>Array.isArray(row.versions)?row.versions.find(version=>version.version===row.latestVersion)||row.versions[0]:null
const activeVisibleVersion=row=>Array.isArray(row.versions)?row.versions.find(version=>version.version===row.activeVersion):null
const skillStages=[{title:'形成私人草稿',description:'从公开链接下载，或编写授权经验'},{title:'规则评测',description:'核对结构、工具权限与适用范围'},{title:'独立审核',description:'主管复核业务适用性与隐私'},{title:'确认发布',description:'发布审核通过的版本，保留回退记录'}]
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
async function refresh(){if(stopped)return;const n=++generation;loading.value=true;error.value='';try{const [identity,list,sourceList,history]=await Promise.all([request.get('/api/organization/me'),request.get('/api/agent/skills'),request.get('/api/agent/skills/sources'),request.get('/api/agent/runs',{params:{limit:50}})]);if(n!==generation)return;if(!Array.isArray(list.data)||!Array.isArray(sourceList.data)||!Array.isArray(history.data))throw Error('技能列表未完整返回');mine.value=identity.data.data;skills.value=list.data;sources.value=sourceList.data;runs.value=history.data.filter(run=>run.status==='COMPLETED')}catch(e){if(n===generation)error.value=e.response?.data?.message||'技能演化尚未启用或服务暂不可用'}finally{if(n===generation)loading.value=false}}
const downloadLabel=status=>({NEEDS_REVIEW:'退出待核对 保留配额',DOWNLOADING:'正在下载与核验',DRAFT_CREATED:'下载完成 已保存',ERROR:'下载失败 请核对来源',DOWNLOADED:'正在创建草稿',NO_CHANGE:'已核对 无版本变化',PURGING:'清理中 结果待核对',PURGED:'文件已清理',CLEANUP_ERROR:'清理未核实 请重试'}[status]||status)
const downloadError=code=>({SOURCE_TIMEOUT:'公开来源响应超时',SOURCE_CONNECTION_FAILED:'公开来源连接失败',DOWNLOAD_EXIT_UNVERIFIED:'尚不能确认下载进程退出 保留目录和配额 不自动重试',DOWNLOAD_NOT_STARTED:'排队任务未启动 已释放预留 可重新发起',SOURCE_AUTHENTICATION_REQUIRED:'来源要求认证 当前未配置',REMOTE_FILE_UNAVAILABLE:'公开来源暂不可访问',MARKET_SOURCE_NOT_VERIFIED:'市场页面的源码无法核验',PUBLIC_REPOSITORY_REQUIRED:'无法确认公开仓库',PUBLIC_SKILL_METADATA_REQUIRED:'公开技能资料不可核验',SKILL_DIRECTORY_AMBIGUOUS:'找到多个技能目录 请提供更明确的链接',SKILL_DIRECTORY_NOT_FOUND:'未找到对应技能目录',LICENSE_REQUIRED:'缺少许可证原文',PACKAGE_LICENSE_REQUIRED:'缺少技能目录适用的许可',SUPPORTED_LICENSE_REQUIRED:'许可无法核实或不在支持范围',LICENSE_DECLARATION_MISMATCH:'市场许可声明与包内许可不一致',PACKAGE_LIMIT_EXCEEDED:'下载包超过文件或大小限制',PACKAGE_STORAGE_LIMIT:'原始快照与技能文件超过存储上限',MARKET_SKILL_NAME_MISMATCH:'源码中的技能名称与市场不一致',REMOTE_BLOB_DIGEST_MISMATCH:'源码字节与固定提交摘要不一致',DOWNLOAD_LEASE_EXPIRED:'下载进程状态需核对',DOWNLOAD_OR_IMPORT_FAILED:'下载或导入未完成 请核对来源与权限'}[code]||'来源核验未通过：'+code)
async function refreshDownloads(){const n=++downloadGeneration;clearTimeout(downloadTimer);if(stopped)return;try{const [result,stats,audit]=await Promise.all([request.get('/api/agent/skills/links'),request.get('/api/agent/skills/links/storage'),request.get('/api/agent/skills/links/storage/audit')]);if(stopped||n!==downloadGeneration)return;downloads.value=result.data;storageStatus.value=stats.data;storageCommands.value=audit.data;linksEnabled.value=true;linkError.value='';if(downloads.value.some(d=>d.status==='DOWNLOADING')){clearTimeout(downloadTimer);downloadTimer=setTimeout(async()=>{await refreshDownloads();await refresh()},2500)}}catch(e){if(stopped||n!==downloadGeneration)return;downloads.value=[];storageStatus.value=null;storageCommands.value=[];linksEnabled.value=false;linkError.value=e.response?.data?.message||'链接安装未启用或服务暂不可用'}}
const mib=value=>knownCount(value)===null?'—':(knownCount(value)/1048576).toFixed(2)
async function cleanupDownload(row){try{await ElMessageBox.confirm('清理本人未被任何技能版本引用的下载缓存 实际删除本地包文件 保留来源记录和清理审计 已审核及历史版本引用的包会拒绝清理','确认清理下载缓存',{confirmButtonText:'确认清理',cancelButtonText:'取消'});busy.value=true;const result=(await request.post('/api/agent/skills/links/downloads/'+row.download_id+'/cleanup',{requestId:crypto.randomUUID(),confirmed:true},{headers})).data;if(result.status!=='COMPLETED')throw new Error('清理结果尚未全部核实 请刷新存储和清理记录');await refreshDownloads()}catch(e){if(e!=='cancel'&&e!=='close')linkError.value=e.response?.data?.message||e.message||'清理结果未核实'}finally{busy.value=false}}
async function installLink(){try{await ElMessageBox.confirm('将从此公开链接下载固定版本到本人后端存储 不运行脚本 不自动启用 下载完成后需规则 Eval 和另一名主管审核','确认链接下载',{confirmButtonText:'确认下载',cancelButtonText:'取消'});linkBusy.value=true;linkError.value='';await request.post('/api/agent/skills/links',{url:linkUrl.value.trim(),targetRole:linkRole.value,requestId:crypto.randomUUID(),confirmed:true},{headers});await refreshDownloads()}catch(e){if(e!=='cancel'&&e!=='close')linkError.value=e.response?.data?.message||'下载结果尚未核实 请刷新核对'}finally{linkBusy.value=false}}
function openUpgrade(){upgradeSkillId=selected.value.skillId;upgradeRevision=selected.value.revision;upgradeUrl.value=latest.value.evidence.sourceUrl;upgradeRequestId=crypto.randomUUID();upgradeError.value='';upgradeOpen.value=true}
async function startUpgrade(){upgradeBusy.value=true;upgradeError.value='';try{await request.post('/api/agent/skills/links/'+upgradeSkillId+'/upgrade',{url:upgradeUrl.value.trim(),expectedRevision:upgradeRevision,requestId:upgradeRequestId,confirmed:true},{headers});upgradeOpen.value=false;await refreshDownloads()}catch(e){upgradeError.value=e.response?.data?.message||'升级下载结果尚未核实 请刷新核对 若更换参数需重新打开升级窗口'}finally{upgradeBusy.value=false}}
async function compareVersions(){comparisonOpen.value=true;comparison.value=null;comparisonError.value='';try{comparison.value=(await request.get('/api/agent/skills/links/'+selected.value.skillId+'/compare',{params:{fromVersion:compareFrom.value,toVersion:compareTo.value}})).data}catch(e){comparisonError.value=e.response?.data?.message||'版本差异暂不可读取 请刷新核对权限和文件完整性'}}
async function uninstallLink(){try{await ElMessageBox.confirm('停止加载本人安装的此技能 保留下载包、许可证、版本及审核审计 之后恢复需再次明确审核版本切换','确认卸载链接技能',{confirmButtonText:'确认卸载',cancelButtonText:'取消'});busy.value=true;selected.value=(await request.post('/api/agent/skills/links/'+selected.value.skillId+'/uninstall',{expectedRevision:selected.value.revision,reason:'用户明确卸载本人链接技能'},{headers})).data;await refresh()}catch(e){if(e!=='cancel'&&e!=='close')dialogError.value=e.response?.data?.message||'卸载结果尚未核实 请刷新核对'}finally{busy.value=false}}
async function capture(){try{await ElMessageBox.confirm('同意从此运行保存成功工具名和完成时间供经验提炼 不保存聊天正文和业务参数','授权经验来源',{confirmButtonText:'明确授权',cancelButtonText:'取消'});busy.value=true;await request.post('/api/agent/skills/sources/'+encodeURIComponent(sourceRunId.value)+'/consent',null,{headers});await refresh()}catch(e){if(e!=='cancel'&&e!=='close')error.value=e.response?.data?.message||'来源授权失败'}finally{busy.value=false}}
function sourceChanged(){form.value.tools=[];sourceTools.value=sources.value.find(source=>source.run_id===form.value.sourceRunId)?.tools||[]}
function newDraft(){editingSkill.value=null;form.value={name:'',targetRole:'INSPECTOR',description:'',instructions:'',sourceRunId:sources.value[0]?.run_id||'',tools:[]};requestId=crypto.randomUUID();dialogError.value='';editing.value=true;sourceChanged()}
async function select(row){if(busy.value||stopped||!row?.skillId)return;const n=++detailGeneration,id=row.skillId;selectedSkillId.value=id;detailLoading.value=true;reason.value='';targetVersion.value=null;businessReviewed.value=false;privacyReviewed.value=false;dialogError.value='';detailOpen.value=true;selected.value=null;try{const value=readSkillView((await request.get('/api/agent/skills/'+id)).data);if(n!==detailGeneration||stopped||!detailOpen.value)return;if(value.skillId!==id)throw Error('技能编号不一致');selected.value=value;compareTo.value=selected.value.versions[0]?.version;compareFrom.value=selected.value.versions[1]?.version||compareTo.value;comparison.value=null}catch(e){if(n===detailGeneration&&!stopped)dialogError.value=e.response?.data?.message||e.message||'技能详情不可用'}finally{if(n===detailGeneration)detailLoading.value=false}}
async function revise(){editingSkill.value=selected.value;const v=latest.value;form.value={name:selected.value.name,targetRole:selected.value.targetRole,description:v.description,instructions:v.instructions,sourceRunId:v.sourceRunId,tools:[...v.tools]};requestId=crypto.randomUUID();dialogError.value='';editing.value=true;sourceTools.value=v.evidence.tools||[]}
async function saveDraft(){if(busy.value||stopped)return;busy.value=true;dialogError.value='';try{const url=editingSkill.value?'/api/agent/skills/'+editingSkill.value.skillId+'/versions?expectedRevision='+editingSkill.value.revision:'/api/agent/skills';const r=await request.post(url,{...form.value,requestId},{headers});if(stopped)return;selected.value=readSkillView(r.data);editing.value=false;detailOpen.value=true;await refresh()}catch(e){if(!stopped)dialogError.value=e.response?.data?.message||'保存结果尚未核实 请刷新后核对'}finally{busy.value=false}}
async function perform(action,extra={}){busy.value=true;dialogError.value='';try{selected.value=(await request.post('/api/agent/skills/'+selected.value.skillId+'/'+action,{expectedRevision:selected.value.revision,...extra},{headers})).data;await refresh()}catch(e){dialogError.value=e.response?.data?.message||'操作结果尚未核实 请刷新后核对'}finally{busy.value=false}}
async function decision(value){try{await ElMessageBox.confirm(value==='APPROVE'?'发布后该角色的助手可在下一轮读取此技能 请再次核对正文、规则评测及脱敏内容':'确认驳回此技能版本','确认审核决定',{confirmButtonText:value==='APPROVE'?'确认发布':'确认驳回',cancelButtonText:'取消'});await perform('decision',{decision:value,reason:reason.value,businessReviewed:businessReviewed.value,privacyReviewed:privacyReviewed.value})}catch{}}
async function rollback(){try{await ElMessageBox.confirm('确认切换到已审核 v'+targetVersion.value+' 后续技能读取将使用该版本','确认版本切换',{confirmButtonText:'确认切换',cancelButtonText:'取消'});await perform('rollback',{targetVersion:targetVersion.value,reason:reason.value})}catch{}}
async function archive(){try{await ElMessageBox.confirm('停用后助手不能继续加载此技能 保留全部版本与审计','确认停用',{confirmButtonText:'确认停用',cancelButtonText:'取消'});await perform('archive',{reason:reason.value})}catch{}}
watch(detailOpen,open=>{if(!open){detailGeneration++;detailLoading.value=false}})
onMounted(async()=>{await refresh();await refreshDownloads()});onBeforeUnmount(()=>{stopped=true;generation++;downloadGeneration++;detailGeneration++;clearTimeout(downloadTimer)})
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
