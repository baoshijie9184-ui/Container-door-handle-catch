<template>
  <div class="page-shell user-manual-page">
    <PageHero title="用户使用手册" description="从图片采集到检测、人工复核和追溯，按当前账号权限完成工作。"><template #actions><router-link class="manual-primary-link" to="/upload"><AppIcon name="Upload" :size="16" />上传图片</router-link><router-link class="manual-secondary-link" to="/inspection/workbench"><AppIcon name="Search" :size="16" />检测工作台</router-link></template></PageHero>
    <div class="manual-account-scope"><AppIcon name="Lock" :size="18" /><p>{{ accountScope }} 私人会话、长期记忆和待确认操作按账号隔离；页面入口不代替服务端授权。</p></div>

    <section class="quick-start-grid">
      <article v-for="step in quickStartSteps" :key="step.title" class="quick-start-card app-panel">
        <div class="manual-step-heading"><span class="step-index">{{ step.index }}</span><AppIcon :name="step.icon" :size="20" /></div>
        <h2>{{ step.title }}</h2>
        <p>{{ step.desc }}</p>
        <router-link :to="step.path">{{ step.action }}<AppIcon name="ArrowRight" :size="15" /></router-link>
      </article>
    </section>

    <section class="role-guide app-panel">
      <div class="section-heading">
        <h2><AppIcon name="User" :size="20" />账号范围与工作入口</h2>
      </div>
      <div class="role-route-grid">
        <article v-for="role in roleGuides" :key="role.name" class="role-route-card">
          <div>
            <h3><AppIcon :name="role.icon" :size="18" />{{ role.name }}</h3>
            <p>{{ role.desc }}</p>
          </div>
          <div class="role-route-links">
            <template v-for="link in role.links" :key="link.path">
              <router-link v-if="!link.supervisorOnly || isSupervisor" :to="link.path">{{ link.label }}<AppIcon name="ArrowRight" :size="13" /></router-link>
              <span v-else class="manual-restricted"><AppIcon name="Lock" :size="13" />{{ link.label }} · 主管</span>
            </template>
          </div>
        </article>
      </div>
    </section>

    <section class="manual-layout">
      <nav class="manual-toc app-panel" aria-label="手册章节">
        <h2>手册目录</h2>
        <button
          v-for="section in sections"
          :key="section.id"
          type="button"
          :aria-current="activeSection===section.id ? 'location' : undefined"
          :class="{ 'is-current':activeSection===section.id }"
          @click="scrollToManualSection(section.id)"
        >
          <AppIcon :name="section.icon" :size="16" />{{ section.title }}
        </button>
      </nav>

      <div class="manual-content">
        <section id="overview" class="manual-section app-panel">
          <div class="section-heading">
            <h2 tabindex="-1"><AppIcon name="HomeFilled" :size="20" />系统能做什么</h2>
          </div>
              <p>
                {{ SYSTEM_NAME }}用于集装箱门把手盖工业缺陷检测，覆盖图像采集、模型推理、检测记录、质检复核、缺陷证据、工单追溯、批次追溯、模型管理、设备人员管理和智能助手辅助查询。
                系统面向单个企业，员工查看本人及分派任务，主管查看企业业务范围。聊天、记忆及操作确认按账号隔离，具体业务操作还受角色和任务状态约束。
              </p>
          <div class="flow-line">
            <span v-for="item in businessFlow" :key="item">{{ item }}</span>
          </div>
        </section>

        <section id="inspection" class="manual-section app-panel">
          <div class="section-heading">
            <h2 tabindex="-1"><AppIcon name="Picture" :size="20" />检测业务怎么用</h2>
          </div>
          <div class="module-grid">
            <article v-for="module in inspectionModules" :key="module.title" class="module-card">
              <div>
                <h3>{{ module.title }}</h3>
                <p>{{ module.desc }}</p>
              </div>
              <router-link :to="module.path">打开模块<AppIcon name="ArrowRight" :size="15" /></router-link>
            </article>
          </div>
        </section>

        <section id="quality" class="manual-section app-panel">
          <div class="section-heading">
            <h2 tabindex="-1"><AppIcon name="DocumentChecked" :size="20" />质检追溯怎么用</h2>
          </div>
          <div class="module-grid">
            <article v-for="module in qualityModules" :key="module.title" class="module-card">
              <div>
                <h3>{{ module.title }}</h3>
                <p>{{ module.desc }}</p>
              </div>
              <router-link :to="module.path">打开模块<AppIcon name="ArrowRight" :size="15" /></router-link>
            </article>
          </div>
        </section>

        <section id="model" class="manual-section app-panel">
          <div class="section-heading">
            <h2 tabindex="-1"><AppIcon name="Tickets" :size="20" />模型中心使用建议</h2>
          </div>
          <ol class="manual-list">
            <li>主管可在模型上传入口提交单个 ONNX 文件（不超过 500 MiB），填写名称、版本，并在更新说明中记录适用缺陷类别。</li>
            <li>上传后查看基础校验回执；基础校验不等同模型效果评估或运行兼容性验收。</li>
            <li>校验通过后再发布模型，生产环境建议只使用已验证模型。</li>
            <li>设置默认模型后，继续观察检测记录和质检反馈，评估模型效果。</li>
          </ol>
          <div class="inline-actions">
            <router-link class="manual-secondary-link" to="/models"><AppIcon name="Tickets" :size="16" />模型管理</router-link>
            <router-link v-if="isSupervisor" class="manual-secondary-link" to="/models/upload"><AppIcon name="Upload" :size="16" />上传模型</router-link>
            <span v-else class="manual-restricted"><AppIcon name="Lock" :size="16" />上传模型由主管操作</span>
          </div>
        </section>

        <section id="resources" class="manual-section app-panel">
          <div class="section-heading">
            <h2 tabindex="-1"><AppIcon name="Monitor" :size="20" />产线资源维护</h2>
          </div>
          <div class="role-grid">
            <article v-for="resource in resources" :key="resource.title">
              <h3><AppIcon :name="resource.icon" :size="18" />{{ resource.title }}</h3>
              <p>{{ resource.desc }}</p>
              <router-link class="manual-resource-link" :to="resource.path">查看资料<AppIcon name="ArrowRight" :size="14" /></router-link>
            </article>
          </div>
        </section>

        <section id="assistant" class="manual-section app-panel">
          <div class="section-heading">
            <h2 tabindex="-1"><AppIcon name="ChatDotRound" :size="20" />智能助手如何协作</h2>
          </div>
          <ol class="assistant-guidance">
            <li v-for="step in assistantGuidance" :key="step.title"><span class="assistant-guidance-icon"><AppIcon :name="step.icon" :size="18" /></span><div><h3>{{ step.title }}</h3><p>{{ step.desc }}</p></div></li>
          </ol>
          <h3 class="manual-subheading">可以这样开始</h3>
          <div class="question-list">
            <div v-for="question in assistantQuestions" :key="question">{{ question }}</div>
          </div>
          <p class="manual-note">
            智能助手用于辅助查询和解释业务，不替代质检人员的最终判断。涉及生产质量结论时，请以质检复核记录和追溯报告为准。
          </p>
          <div class="inline-actions"><router-link class="manual-secondary-link" to="/agent/chat"><AppIcon name="ChatDotRound" :size="16" />打开智能助手</router-link><router-link class="manual-secondary-link" to="/agent/trace"><AppIcon name="DocumentChecked" :size="16" />核对执行轨迹</router-link></div>
        </section>

        <section id="faq" class="manual-section app-panel">
          <div class="section-heading">
            <h2 tabindex="-1"><AppIcon name="Search" :size="20" />常见问题</h2>
          </div>
          <label class="manual-faq-label" for="manual-faq-search">搜索本页常见问题</label>
          <el-input id="manual-faq-search" v-model="faqQuery" clearable placeholder="例如：上传、排队、模型、待核对" @keydown.esc="faqQuery=''" />
          <p class="manual-faq-count" role="status">{{ filteredFaqs.length }} / {{ faqs.length }} 条说明 · 仅搜索本页内容</p>
          <div v-if="!filteredFaqs.length" class="manual-faq-empty"><AppIcon name="Search" :size="20" /><p>没有匹配的常见问题，试试更短的关键词</p><el-button @click="faqQuery=''">显示全部问题</el-button></div>
          <el-collapse v-else>
            <el-collapse-item
              v-for="item in filteredFaqs"
              :key="item.question"
              :title="item.question"
              :name="item.question"
            >
              <p>{{ item.answer }}</p>
              <pre v-if="item.command" class="manual-command">{{ item.command }}</pre>
            </el-collapse-item>
          </el-collapse>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup>
import {SYSTEM_NAME} from '@/utils/systemBrand'
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useUserStore } from '@/stores/user'
const user = useUserStore()
const isSupervisor = computed(() => user.isAuthenticated && user.role === 'SUPERVISOR')
const faqQuery = ref('')
const activeSection = ref('overview')
let sectionObserver
const visibleSections = new Set()
onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') return
  sectionObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) visibleSections.add(entry.target)
      else visibleSections.delete(entry.target)
    }
    const nearest = [...visibleSections].sort((left,right) => left.getBoundingClientRect().top-right.getBoundingClientRect().top)[0]
    if (nearest) activeSection.value = nearest.id
  }, { rootMargin:'-15% 0px -55% 0px', threshold:0 })
  for (const section of document.querySelectorAll('.user-manual-page .manual-section')) sectionObserver.observe(section)
})
onBeforeUnmount(() => { sectionObserver?.disconnect(); visibleSections.clear() })
const accountScope = computed(() => user.role === 'SUPERVISOR' ? '当前为主管视角，可查看企业业务范围。' : ['INSPECTOR','OPERATOR'].includes(user.role) ? '当前为员工视角，业务数据限于本人及分派任务。' : '当前业务范围以账号授权为准。')
function scrollToManualSection(sectionId) {
  const target = document.getElementById(sectionId)
  if (!target) return
  activeSection.value = sectionId
  const heading = target.querySelector('h2')
  heading?.focus({ preventScroll:true })
  target.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
}

const sections = [
  { id: 'overview', title: '系统概览', icon:'HomeFilled' },
  { id: 'inspection', title: '检测业务', icon:'Picture' },
  { id: 'quality', title: '质检追溯', icon:'DocumentChecked' },
  { id: 'model', title: '模型中心', icon:'Tickets' },
  { id: 'resources', title: '产线资源', icon:'Monitor' },
  { id: 'assistant', title: '智能助手', icon:'ChatDotRound' },
  { id: 'faq', title: '常见问题', icon:'Search' }
]

const quickStartSteps = [
  { index: '01', icon:'Upload', title: '上传图片', desc: '上传门把手原图，补齐批次、工单与设备等采集信息。', path: '/upload', action: '去上传' },
  { index: '02', icon:'Search', title: '核对检测', desc: '采集上传会自动提交检测，到工作台核对实际进度、模型记录和输出。', path: '/inspection/workbench', action: '查看进度' },
  { index: '03', icon:'DocumentChecked', title: '人工复核', desc: '根据任务状态完成复核、处置及必要的返工复检；报告单独审批。', path: '/quality/queue', action: '去复核' },
  { index: '04', icon:'Collection', title: '追溯核对', desc: '按工单或批次查看证据与闭环状态，不将生成摘要当作归档或审批完成。', path: '/quality/work-order-trace', action: '去追溯' }
]

const businessFlow = ['图像采集', '模型检测', '检测记录', '质检复核', '缺陷证据', '工单追溯', '批次追溯']

const roleGuides = [
  {
    name: '员工',
    icon: 'User',
    desc: '查看本人及分派任务，完成获准的采集、检测与质检工作。私人聊天和记忆按账号隔离。',
    links: [
      { label: '图像采集上传', path: '/upload' },
      { label: '检测工作台', path: '/inspection/workbench' },
      { label: '检测记录', path: '/inspection/history' }
    ]
  },
  {
    name: '质检工作',
    icon: 'DocumentChecked',
    desc: '这是工作内容说明，不是额外账号角色。能否分派、复核、处置或放行，以当前角色及任务状态为准。',
    links: [
      { label: '质检队列', path: '/quality/queue' },
      { label: '缺陷证据库', path: '/quality/evidence' },
      { label: '工单追溯', path: '/quality/work-order-trace' }
    ]
  },
  {
    name: '模型维护工作',
    icon: 'Tickets',
    desc: '核对模型文件、版本、评估与发布状态；基础校验通过不表示检测效果合格。',
    links: [
      { label: '模型管理', path: '/models' },
      { label: '上传模型', path: '/models/upload', supervisorOnly:true },
      { label: '检测记录', path: '/inspection/history' }
    ]
  },
  {
    name: '主管',
    icon: 'Collection',
    desc: '查看企业业务与待办，进行授权的分派、维护和独立审批；不读取其他账号私人会话。',
    links: [
      { label: '首页总览', path: '/home' },
      { label: '批次追溯', path: '/quality/batch-trace' },
      { label: '设备使用记录', path: '/device-records' }
    ]
  }
]

const inspectionModules = [
  { title: '图像采集上传', path: '/upload', desc: '上传原始图片，创建检测任务，并补充工单、批次、设备、人员等追溯字段。' },
  { title: '检测工作台', path: '/inspection/workbench', desc: '核对采集上传已提交任务的阶段、模型与结果；独立单图检测入口另行选择图片、模型与阈值。' },
  { title: '检测记录', path: '/inspection/history', desc: '查询历史任务，复查检测结果，定位异常任务并查看检测报告。' }
]

const qualityModules = [
  { title: '质检队列', path: '/quality/queue', desc: '查看待复核、待处置、待返工、需复检或暂挂任务，按当前账号及任务允许的动作处理。' },
  { title: '缺陷证据库', path: '/quality/evidence', desc: '集中查看缺陷图片、类别、置信度、严重等级和模型证据链。' },
  { title: '工单追溯', path: '/quality/work-order-trace', desc: '按工单号回溯检测任务、质检记录、操作人员和报告。' },
  { title: '批次追溯', path: '/quality/batch-trace', desc: '按批次号查看整体检测质量、缺陷分布和异常来源。' }
]

const resources = [
  { title: '设备管理', icon:'Monitor', path:'/devices', desc: '查看登记编号、型号、业务状态与使用员工。使用状态不等于在线心跳；主管执行获准的资料及关系维护。' },
  { title: '设备使用记录', icon:'Clock', path:'/device-records', desc: '查看设备使用及归还的历史快照。新增使用登记还会更新当前设备状态与使用员工，请主管先核对关系变化。' },
  { title: '人员管理', icon:'User', path:'/employees', desc: '核对采集、检测与维修人员资料，支撑操作追溯；人员登记与登录账号角色分别管理，维护由主管执行。' },
  { title: '账号与组织', icon:'Connection', path:'/organization', desc: '查看本人账号关联。主管维护部门及账号人员关联；资料关联不自动改变账号角色或完成历史任务归属回填。' }
]

const assistantGuidance = [
  { title:'选择模型并补充资料', icon:'Files', desc:'在输入区选择本次会话模型，使用加号上传资料并通过 @文件 引用。模型目录登记不代表供应商实时可用，实际执行模型以运行记录为准。' },
  { title:'区分计划、提问和操作确认', icon:'DocumentChecked', desc:'复杂工作可用 /plan 先审计划；参数不足时回答提问卡片。批准计划或回答问题不替代敏感操作确认，质检放行与报告审批仍在业务页面完成。' },
  { title:'排队或引导后续要求', icon:'ChatDotRound', desc:'任务执行时可排队补充消息，逐条编辑、撤回或选择引导。没有排队消息时不展示队列；暂停后按界面提示继续，不重复创建原任务。' },
  { title:'核对过程与产物', icon:'Collection', desc:'在工作面板查看任务、子 Agent、文件、用量及执行证据。HTML/SVG 按源码查看；用量缺失是未知，估算值不作为账单。结果待核对时保留原请求编号，不直接重发。' }
]

const assistantQuestions = [
  '今天有哪些待复核任务？',
  '帮我查看某个批次的检测结果。',
  '模型管理在哪里？',
  '质检队列有哪些状态？',
  '某个工单的追溯链路怎么看？'
]

const faqs = [
  { question: '登录后看不到数据怎么办？', answer: '先核对筛选与当前账号范围。读取失败时按页面提示重新读取；员工只能查看本人及分派任务，权限或分派不符请联系主管。' },
  {
    question: '没有工单或批次记录怎么办？',
    answer: '先核对账号范围、任务绑定的工单或批次编号，以及当前筛选条件。暂无记录不代表服务异常；需要业务数据时，从图片采集流程创建真实任务，不根据空列表直接导入预置数据。'
  },
  { question: '检测任务一直未完成怎么办？', answer: '查看任务当前阶段、错误说明及追溯记录；结果待核对时保留任务和请求编号，不要直接重复创建或重试，联系主管核对原回执。' },
  { question: '质检队列没有任务怎么办？', answer: '逐项核对状态筛选、账号任务范围和分派情况。没有匹配任务不表示系统异常，读取失败请使用页面的重新读取入口。' },
  { question: '工单或批次追溯查不到结果怎么办？', answer: '确认编号准确、任务已绑定该编号且在当前账号权限内。查询摘要成功不代表所有关联任务、质量处置或报告审批已完成。' },
  { question: '模型重新校验失败怎么办？', answer: '检查模型文件是否存在、格式是否正确、元数据是否完整以及推理环境是否兼容。' },
  { question: '模型上传支持哪些文件？', answer: '当前模型上传页面由主管操作，仅选择单个非空 ONNX 文件，最大 500 MiB。服务端已有 PTH 检测模型不代表此上传入口支持 PTH，基础校验通过也不等于效果评估通过。' },
  { question: '为什么没有显示聊天排队区域？', answer: '没有等待消息时队列隐藏。执行中发送后续要求后再核对队列，可使用编辑、撤回或引导；暂停和继续沿用当前任务，不自动重发业务操作。' },
  { question: '上传或操作提示结果待核对怎么办？', answer: '保留请求编号、资源编号及提示时间，先查原记录和审计。刷新、重读当前资料或离开页面不会取消已被服务器接收的操作，也不能据此证明原操作失败；不要直接重新提交。' },
  { question: '切换 LLM 模型会改变系统默认模型吗？', answer: '输入区选择是会话执行选择，系统默认及备用顺序由主管模型配置管理。可选目录不等于实时连通或余额充足，备用切换和实际使用模型应核对执行记录。' },
  { question: '为什么附件不能直接打开为网页？', answer: '上传、预览和读取仍受账号与文件权限限制。HTML/SVG 仅展示源码，不直接执行；图片识别和扫描 PDF 的能力以当前模型及工具为准，不能将上传成功当作内容已被读取。' }
]
const filteredFaqs = computed(() => {
  const query=faqQuery.value.trim().toLocaleLowerCase('zh-CN')
  return query ? faqs.filter(item=>(item.question+' '+item.answer).toLocaleLowerCase('zh-CN').includes(query)) : faqs
})
</script>

<style lang="scss" scoped>
.user-manual-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.quick-start-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.quick-start-card {
  padding: 20px;
  border-color: rgba(37, 99, 235, 0.10);
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 30px;
  border-radius: 999px;
  color: var(--app-primary);
  background: rgba(37, 99, 235, 0.10);
  font-weight: 900;
}

.quick-start-card h2 {
  margin: 16px 0 8px;
  color: var(--app-text);
  font-size: 18px;
}

.quick-start-card p {
  min-height: 66px;
  margin: 0 0 14px;
  color: var(--app-text-secondary);
  line-height: 1.65;
}

.quick-start-card a,
.module-card a,
.manual-toc button,
.role-route-links a {
  color: var(--app-primary);
  font-weight: 800;
  text-decoration: none;
}

.role-guide {
  padding: 24px;
}

.role-route-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.role-route-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 18px;
  min-height: 210px;
  padding: 18px;
  border: 1px solid rgba(37, 99, 235, 0.10);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(239, 246, 255, 0.55));
}

.role-route-card h3 {
  margin: 0 0 8px;
  color: var(--app-text);
  font-size: 18px;
}

.role-route-card p {
  margin: 0;
  color: var(--app-text-secondary);
  line-height: 1.7;
}

.role-route-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.role-route-links a {
  padding: 8px 10px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
}

.manual-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.manual-toc {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
}

.manual-toc h2 {
  margin: 0 0 8px;
  color: var(--app-text);
  font-size: 18px;
}

.manual-toc button {
  padding: 10px 12px;
  border: 0;
  border-radius: 12px;
  color: var(--app-text-secondary);
  background: transparent;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition: color 180ms ease, background-color 180ms ease;
}

.manual-toc button:hover {
  color: var(--app-primary);
  background: rgba(37, 99, 235, 0.08);
}

.manual-content {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.manual-section {
  padding: 24px;
}

.section-heading span {
  color: var(--app-primary);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.section-heading h2 {
  margin: 8px 0 16px;
  color: var(--app-text);
  font-size: 24px;
}

.manual-section p {
  color: var(--app-text-secondary);
  line-height: 1.75;
}

.flow-line {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}

.flow-line span {
  padding: 10px 14px;
  border-radius: 999px;
  color: var(--app-primary);
  background: rgba(37, 99, 235, 0.08);
  font-weight: 800;
}

.module-grid,
.role-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.module-card,
.role-grid article {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 18px;
  border: 1px solid rgba(37, 99, 235, 0.10);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.62);
}

.module-card h3,
.role-grid h3 {
  margin: 0 0 8px;
  color: var(--app-text);
  font-size: 17px;
}

.module-card p,
.role-grid p {
  margin: 0;
}

.module-card a {
  flex-shrink: 0;
  align-self: center;
}

.manual-list {
  margin: 0;
  padding-left: 20px;
  color: var(--app-text-secondary);
  line-height: 1.9;
}

.inline-actions {
  display: flex;
  gap: 12px;
  margin-top: 18px;
}

.question-list {
  display: grid;
  gap: 10px;
}

.question-list div {
  padding: 13px 16px;
  border-radius: 14px;
  color: var(--app-text);
  background: linear-gradient(90deg, rgba(37, 99, 235, 0.08), rgba(14, 165, 233, 0.04));
  font-weight: 700;
}

.manual-note {
  margin-top: 18px;
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid rgba(245, 158, 11, 0.18);
  background: rgba(245, 158, 11, 0.08);
}

.manual-command {
  margin: 12px 0 0;
  padding: 12px 14px;
  border: 1px solid rgba(15, 118, 110, 0.18);
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.92);
  color: #d1fae5;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.manual-restricted {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 7px;
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 1.8;
}

.inline-actions { align-items: center; }
.role-grid article { flex-direction: column; gap: 10px; min-width: 0; }
.role-grid h3 { display: flex; align-items: center; gap: 8px; }
.role-grid h3 .el-icon { color: var(--app-primary); flex-shrink: 0; }
.manual-resource-link { display: inline-flex; align-items: center; gap: 6px; align-self: flex-start; color: var(--app-primary); font-size: 12px; line-height: 1.8; text-decoration: none; }
.assistant-guidance { display: grid; gap: 0; padding: 0; margin: 0 0 24px; list-style: none; }
.assistant-guidance li { display: flex; align-items: flex-start; gap: 12px; border-top: 1px solid var(--app-border); padding: 16px 0; }
.assistant-guidance li > div { min-width: 0; }
.assistant-guidance-icon { display: grid; place-items: center; flex: 0 0 32px; width: 32px; height: 32px; border-radius: 8px; color: var(--app-primary); background: var(--app-primary-soft); }
.assistant-guidance h3,.manual-subheading { color: var(--app-text); font-size: 14px; font-weight: 600; line-height: 1.8; margin: 0 0 6px; }
.assistant-guidance p { margin: 0; }
.manual-subheading { margin-bottom: 12px; }
.manual-faq-label { display: block; margin: 0 0 8px; color: var(--app-text); font-size: 13px; font-weight: 550; }
.manual-faq-count { margin: 8px 0 16px; color: var(--app-text-secondary); }
.manual-faq-empty { display: flex; align-items: flex-start; flex-direction: column; gap: 10px; padding: 16px 0; color: var(--app-primary); }
.manual-faq-empty p { margin: 0; }
.user-manual-page :is(a,button,summary):focus-visible { outline: 2px solid var(--app-primary); outline-offset: 3px; }
.manual-resource-link { transition: color 180ms ease, transform 180ms ease; }
.manual-resource-link:hover { color: var(--app-primary-hover); text-decoration: underline; text-underline-offset: 3px; }
.manual-resource-link:active { transform: scale(.98); }
@media(prefers-reduced-motion:reduce) { .manual-resource-link,.manual-toc button { transition: none; transform: none; } }

@media (max-width: 1100px) {
  .manual-layout {
    grid-template-columns: 1fr;
  }

  .quick-start-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .role-route-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .manual-toc {
    position: static;
  }
}

@media (max-width: 720px) {
  .quick-start-grid,
  .role-route-grid,
  .module-grid,
  .role-grid {
    grid-template-columns: 1fr;
  }

  .module-card {
    flex-direction: column;
  }
}
</style>
