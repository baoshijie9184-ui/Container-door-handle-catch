<template>
  <div class="page-shell user-manual-page">
    <section class="page-hero manual-hero command-panel">
      <div>
        <span class="page-hero-label">User Guide</span>
        <h1 class="page-hero-title">用户使用手册</h1>
        <p class="page-hero-text">
          用一页说明快速了解系统怎么登录、怎么检测、怎么复核、怎么追溯，以及各角色应该优先使用哪些模块。
        </p>
        <div class="manual-actions">
          <router-link to="/upload">
            <el-button type="primary">开始图像采集</el-button>
          </router-link>
          <router-link to="/inspection/workbench">
            <el-button plain>进入检测工作台</el-button>
          </router-link>
          <router-link to="/quality/queue">
            <el-button plain>查看质检队列</el-button>
          </router-link>
        </div>
      </div>
      <div class="manual-hero-card">
        <div class="manual-hero-card-label">推荐流程</div>
        <strong>上传图片 -> 模型检测 -> 质检复核 -> 证据沉淀 -> 工单/批次追溯</strong>
        <span>按这个顺序操作，可以最快形成完整工业检测闭环。</span>
      </div>
    </section>

    <section class="quick-start-grid">
      <article v-for="step in quickStartSteps" :key="step.title" class="quick-start-card app-panel">
        <div class="step-index">{{ step.index }}</div>
        <h2>{{ step.title }}</h2>
        <p>{{ step.desc }}</p>
        <router-link :to="step.path">{{ step.action }}</router-link>
      </article>
    </section>

    <section class="role-guide app-panel">
      <div class="section-heading">
        <span>Role Guide</span>
        <h2>按角色快速找到该用的功能</h2>
      </div>
      <div class="role-route-grid">
        <article v-for="role in roleGuides" :key="role.name" class="role-route-card">
          <div>
            <h3>{{ role.name }}</h3>
            <p>{{ role.desc }}</p>
          </div>
          <div class="role-route-links">
            <router-link v-for="link in role.links" :key="link.path" :to="link.path">
              {{ link.label }}
            </router-link>
          </div>
        </article>
      </div>
    </section>

    <section class="manual-layout">
      <aside class="manual-toc app-panel">
        <h2>手册目录</h2>
        <button
          v-for="section in sections"
          :key="section.id"
          type="button"
          @click="scrollToManualSection(section.id)"
        >
          {{ section.title }}
        </button>
      </aside>

      <div class="manual-content">
        <section id="overview" class="manual-section app-panel">
          <div class="section-heading">
            <span>Overview</span>
            <h2>系统能做什么</h2>
          </div>
              <p>
                本系统用于集装箱门把手工业缺陷检测，覆盖图像采集、模型推理、检测记录、质检复核、缺陷证据、工单追溯、批次追溯、模型管理、设备人员管理和智能助手辅助查询。
                系统面向单个企业，所有已登录用户共享业务与聊天数据，并拥有相同的操作能力。
              </p>
          <div class="flow-line">
            <span v-for="item in businessFlow" :key="item">{{ item }}</span>
          </div>
        </section>

        <section id="inspection" class="manual-section app-panel">
          <div class="section-heading">
            <span>Inspection</span>
            <h2>检测业务怎么用</h2>
          </div>
          <div class="module-grid">
            <article v-for="module in inspectionModules" :key="module.title" class="module-card">
              <div>
                <h3>{{ module.title }}</h3>
                <p>{{ module.desc }}</p>
              </div>
              <router-link :to="module.path">打开模块</router-link>
            </article>
          </div>
        </section>

        <section id="quality" class="manual-section app-panel">
          <div class="section-heading">
            <span>Quality Trace</span>
            <h2>质检追溯怎么用</h2>
          </div>
          <div class="module-grid">
            <article v-for="module in qualityModules" :key="module.title" class="module-card">
              <div>
                <h3>{{ module.title }}</h3>
                <p>{{ module.desc }}</p>
              </div>
              <router-link :to="module.path">打开模块</router-link>
            </article>
          </div>
        </section>

        <section id="model" class="manual-section app-panel">
          <div class="section-heading">
            <span>Model Ops</span>
            <h2>模型中心使用建议</h2>
          </div>
          <ol class="manual-list">
            <li>上传新模型时填写清楚模型名称、版本、适用缺陷类别和说明。</li>
            <li>上传后先执行模型校验，确认文件完整、格式正确、推理环境兼容。</li>
            <li>校验通过后再发布模型，生产环境建议只使用已验证模型。</li>
            <li>设置默认模型后，继续观察检测记录和质检反馈，评估模型效果。</li>
          </ol>
          <div class="inline-actions">
            <router-link to="/models">
              <el-button type="primary" plain>模型管理</el-button>
            </router-link>
            <router-link to="/models/upload">
              <el-button plain>上传模型</el-button>
            </router-link>
          </div>
        </section>

        <section id="resources" class="manual-section app-panel">
          <div class="section-heading">
            <span>Resources</span>
            <h2>产线资源维护</h2>
          </div>
          <div class="role-grid">
            <article v-for="resource in resources" :key="resource.title">
              <h3>{{ resource.title }}</h3>
              <p>{{ resource.desc }}</p>
            </article>
          </div>
        </section>

        <section id="assistant" class="manual-section app-panel">
          <div class="section-heading">
            <span>AI Assistant</span>
            <h2>智能助手可以怎么问</h2>
          </div>
          <div class="question-list">
            <div v-for="question in assistantQuestions" :key="question">{{ question }}</div>
          </div>
          <p class="manual-note">
            智能助手用于辅助查询和解释业务，不替代质检人员的最终判断。涉及生产质量结论时，请以质检复核记录和追溯报告为准。
          </p>
        </section>

        <section id="faq" class="manual-section app-panel">
          <div class="section-heading">
            <span>FAQ</span>
            <h2>常见问题</h2>
          </div>
          <el-collapse>
            <el-collapse-item
              v-for="item in faqs"
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
function scrollToManualSection(sectionId) {
  const target = document.getElementById(sectionId)
  if (!target) return
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const sections = [
  { id: 'overview', title: '系统概览' },
  { id: 'inspection', title: '检测业务' },
  { id: 'quality', title: '质检追溯' },
  { id: 'model', title: '模型中心' },
  { id: 'resources', title: '产线资源' },
  { id: 'assistant', title: '智能助手' },
  { id: 'faq', title: '常见问题' }
]

const quickStartSteps = [
  { index: '01', title: '上传图片', desc: '将门把手原图上传入库，绑定批次、工单、设备等追溯信息。', path: '/upload', action: '去上传' },
  { index: '02', title: '执行检测', desc: '在检测工作台选择模型和阈值，查看任务状态与模型推理结果。', path: '/inspection/workbench', action: '去检测' },
  { index: '03', title: '质检复核', desc: '对待复核任务进行确认、处置、返工或报告导出。', path: '/quality/queue', action: '去复核' },
  { index: '04', title: '追溯归档', desc: '按工单或批次回看检测链路，沉淀缺陷证据。', path: '/quality/work-order-trace', action: '去追溯' }
]

const businessFlow = ['图像采集', '模型检测', '检测记录', '质检复核', '缺陷证据', '工单追溯', '批次追溯']

const roleGuides = [
  {
    name: '检测操作员',
    desc: '重点完成图片上传、任务创建、检测执行和结果初看。',
    links: [
      { label: '图像采集上传', path: '/upload' },
      { label: '检测工作台', path: '/inspection/workbench' },
      { label: '检测记录', path: '/inspection/history' }
    ]
  },
  {
    name: '质检员',
    desc: '重点处理复核队列、确认缺陷证据并完成质量闭环。',
    links: [
      { label: '质检队列', path: '/quality/queue' },
      { label: '缺陷证据库', path: '/quality/evidence' },
      { label: '工单追溯', path: '/quality/work-order-trace' }
    ]
  },
  {
    name: '模型维护人员',
    desc: '重点维护模型版本、发布默认模型并观察质检反馈。',
    links: [
      { label: '模型管理', path: '/models' },
      { label: '上传模型', path: '/models/upload' },
      { label: '检测记录', path: '/inspection/history' }
    ]
  },
  {
    name: '产线负责人',
    desc: '重点关注全局态势、批次质量和设备人员状态。',
    links: [
      { label: '首页总览', path: '/home' },
      { label: '批次追溯', path: '/quality/batch-trace' },
      { label: '设备使用记录', path: '/device-records' }
    ]
  }
]

const inspectionModules = [
  { title: '图像采集上传', path: '/upload', desc: '上传原始图片，创建检测任务，并补充工单、批次、设备、人员等追溯字段。' },
  { title: '检测工作台', path: '/inspection/workbench', desc: '选择模型、设置阈值、执行检测，查看任务列表、检测进度和结果证据。' },
  { title: '检测记录', path: '/inspection/history', desc: '查询历史任务，复查检测结果，定位异常任务并查看检测报告。' }
]

const qualityModules = [
  { title: '质检队列', path: '/quality/queue', desc: '处理待分配、待复核、复核中、已通过、需返工等状态任务。' },
  { title: '缺陷证据库', path: '/quality/evidence', desc: '集中查看缺陷图片、类别、置信度、严重等级和模型证据链。' },
  { title: '工单追溯', path: '/quality/work-order-trace', desc: '按工单号回溯检测任务、质检记录、操作人员和报告。' },
  { title: '批次追溯', path: '/quality/batch-trace', desc: '按批次号查看整体检测质量、缺陷分布和异常来源。' }
]

const resources = [
  { title: '设备管理', desc: '维护采集设备、检测设备、在线状态、设备负责人和设备位置。' },
  { title: '设备使用记录', desc: '查看设备调用记录，排查某台设备是否集中产生异常任务。' },
  { title: '人员管理', desc: '维护采集、检测、维修、质检等人员信息，支撑操作追溯。' }
]

const assistantQuestions = [
  '今天有哪些待复核任务？',
  '帮我查看某个批次的检测结果。',
  '模型管理在哪里？',
  '质检队列有哪些状态？',
  '某个工单的追溯链路怎么看？'
]

const faqs = [
  { question: '登录后看不到数据怎么办？', answer: '先清空筛选条件并刷新页面；如果仍无数据，检查后端服务、数据库连接和当前账号权限。' },
  {
    question: '首次验收没有工单、批次、质检数据怎么办？',
    answer: '这是空库的正常现象。可在启动后端前开启业务预置数据导入，系统会自动写入模型、设备、质检队列、缺陷证据、工单追溯和批次追溯数据。真实生产库请保持该开关关闭。',
    command: 'PowerShell:\n.\\scripts\\start-backend-with-business-seed.ps1\n\n或手动设置：\n$env:APP_BUSINESS_SEED_ENABLED="true"\n.\\mvnw.cmd spring-boot:run'
  },
  { question: '检测任务一直未完成怎么办？', answer: '通常需要检查推理服务、远程检测服务、OSS 图片路径和模型状态是否正常。' },
  { question: '质检队列没有任务怎么办？', answer: '可能当前没有需要复核的任务，也可能筛选状态不匹配，建议切换到全部可处理后刷新。' },
  { question: '工单或批次追溯查不到结果怎么办？', answer: '确认工单号或批次号是否准确，且相关检测任务已经完成并绑定了追溯字段。' },
  { question: '模型重新校验失败怎么办？', answer: '检查模型文件是否存在、格式是否正确、元数据是否完整以及推理环境是否兼容。' }
]
</script>

<style lang="scss" scoped>
.user-manual-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.manual-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 24px;
  align-items: stretch;
}

.manual-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 22px;
}

.manual-hero-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
  padding: 22px;
  border-radius: 22px;
  color: #fff;
  background:
    radial-gradient(circle at 16% 18%, rgba(56, 189, 248, 0.34), transparent 38%),
    linear-gradient(135deg, #10233f, #16436f 58%, #0f766e);
  box-shadow: 0 18px 40px rgba(15, 47, 87, 0.24);
}

.manual-hero-card-label {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  opacity: 0.72;
  font-weight: 800;
}

.manual-hero-card strong {
  font-size: 20px;
  line-height: 1.45;
}

.manual-hero-card span {
  color: rgba(255, 255, 255, 0.72);
  line-height: 1.7;
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
  transition: all 0.2s;
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

@media (max-width: 1100px) {
  .manual-hero,
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
