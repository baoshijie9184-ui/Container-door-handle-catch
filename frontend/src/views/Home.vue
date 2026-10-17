<template>
  <div class="home-page">
    <!-- ═══ 加载骨架屏 ═══ -->
    <template v-if="pageLoading">
      <section class="hero-grid">
        <div class="hero-panel app-panel" style="padding:28px">
          <div class="skeleton skeleton-title" style="width:40%"></div>
          <div class="skeleton skeleton-text" style="width:75%"></div>
          <div class="skeleton skeleton-text" style="width:55%"></div>
          <div style="display:flex;gap:12px;margin-top:24px">
            <div class="skeleton" style="width:140px;height:40px;border-radius:10px"></div>
            <div class="skeleton" style="width:140px;height:40px;border-radius:10px"></div>
          </div>
          <div class="hero-highlights">
            <div class="skeleton skeleton-card"></div>
            <div class="skeleton skeleton-card"></div>
            <div class="skeleton skeleton-card"></div>
          </div>
        </div>
        <div class="status-panel app-panel" style="padding:28px">
          <div class="skeleton skeleton-title" style="width:50%"></div>
          <div class="skeleton skeleton-text" style="width:70%"></div>
          <div v-for="i in 3" :key="i" style="margin-top:16px">
            <div class="skeleton" style="height:60px;border-radius:16px"></div>
          </div>
        </div>
      </section>
      <section class="content-grid">
        <div v-for="i in 7" :key="i" class="skeleton skeleton-chart" style="grid-column: span 4"></div>
      </section>
    </template>

    <!-- ═══ 真实内容 ═══ -->
    <template v-else>
    <div role="status" class="dashboard-refresh-note">
      <span>{{ refreshing ? '正在刷新…' : '每 30 秒自动刷新（后台页面暂停）' }}</span>
      <span v-if="lastUpdated"> · 最近全部更新成功：{{ lastUpdated }}</span>
      <el-alert v-if="failedSections.length" type="warning" :closable="false"
        :title="`加载失败：${failedSections.join('、')}。对应区域可能保留旧数据；首次加载失败的零值不代表真实统计，请刷新重试。`" />
    </div>
    <!-- ── 顶部 Hero + 运行态势 ── -->
    <section class="hero-grid animate-fade-in-up">
      <div class="hero-panel app-panel command-panel">
        <div class="hero-copy">
          <div class="industrial-kicker">Door Handle Inspection Center</div>
          <h2 class="hero-title">让每一次检测都有据可循</h2>
          <p class="hero-text">
            统一查看检测趋势、设备状态与人员分布，帮助现场团队更快定位异常、安排巡检和处理维护任务。
          </p>
        </div>

        <div class="hero-telemetry">
          <span class="metric-chip">在线设备 {{ deviceStatus.online }} 台</span>
          <span class="metric-chip">在岗人员 {{ employeeStatus.active }} 人</span>
          <span class="metric-chip">平均漏检率 {{ formatPercent(avgMissRate) }}</span>
        </div>

        <div class="hero-actions">
          <el-button type="primary" @click="router.push('/inspection/workbench')">
            <el-icon style="margin-right:6px"><Search /></el-icon>
            开始图像检测
          </el-button>
          <el-button plain @click="router.push('/models')">
            <el-icon style="margin-right:6px"><Setting /></el-icon>
            管理检测模型
          </el-button>
          <el-button plain @click="router.push('/agent/chat')">向 AI 助手提问 <el-icon style="margin-left:4px"><ArrowRight /></el-icon></el-button>
        </div>

        <div class="hero-highlights">
          <div class="highlight-card hl-primary">
            <div class="hl-header">
              <div class="hl-icon hl-icon-blue">
                <el-icon><DataAnalysis /></el-icon>
              </div>
              <span class="hl-trend up">累计</span>
            </div>
            <strong class="hl-value">{{ formatNumber(totalDetections) }}</strong>
            <span class="hl-label">累计完成检测任务数（含部分失败）</span>
          </div>
          <div class="highlight-card hl-success">
            <div class="hl-header">
              <div class="hl-icon hl-icon-green">
                <el-icon><Monitor /></el-icon>
              </div>
              <span class="hl-trend up">{{ deviceStatus.online }} 在线</span>
            </div>
            <strong class="hl-value">{{ onlineRate }}<small>%</small></strong>
            <span class="hl-label">设备在线率</span>
          </div>
          <div class="highlight-card hl-warning">
            <div class="hl-header">
              <div class="hl-icon hl-icon-amber">
                <el-icon><User /></el-icon>
              </div>
              <span class="hl-trend">{{ employeeStatus.active }} 在岗</span>
            </div>
            <strong class="hl-value">{{ employeeActiveRate }}<small>%</small></strong>
            <span class="hl-label">人员在岗率</span>
          </div>
        </div>
      </div>

      <div class="status-panel app-panel">
        <div class="status-header">
          <div>
            <h3 class="app-panel-title">运行态势</h3>
            <p class="app-panel-subtitle">实时运营摘要</p>
          </div>
          <el-button text size="small" @click="refreshAll">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>

        <div class="status-list">
          <div class="status-item interactive" @click="router.push('/devices')">
            <div class="si-indicator si-online">
              <span class="pulse-dot"></span>
            </div>
            <div class="si-body">
              <div class="si-title">设备在线 <em>{{ deviceStatus.online }}</em> 台</div>
              <div class="si-desc">
                <span class="si-metric">离线 {{ deviceStatus.offline }}</span>
                <span class="si-sep">|</span>
                <span class="si-metric">未使用 {{ deviceStatus.unused }}</span>
              </div>
              <div class="si-bar"><div class="si-bar-fill" :style="{ width: onlineRate + '%' }"></div></div>
            </div>
            <el-icon class="si-arrow"><ArrowRight /></el-icon>
          </div>
          <div class="status-item interactive" @click="router.push('/devices')">
            <div class="si-indicator si-maintain">
              <el-icon><WarningFilled /></el-icon>
            </div>
            <div class="si-body">
              <div class="si-title">维护关注 <em>{{ deviceStatus.maintenance }}</em> 台</div>
              <div class="si-desc">设备维护中，需安排检修</div>
              <div class="si-bar"><div class="si-bar-fill si-bar-warn" :style="{ width: maintenanceRate + '%' }"></div></div>
            </div>
            <el-icon class="si-arrow"><ArrowRight /></el-icon>
          </div>
          <div class="status-item interactive" @click="router.push('/employees')">
            <div class="si-indicator si-schedule">
              <el-icon><UserFilled /></el-icon>
            </div>
            <div class="si-body">
              <div class="si-title">人员排班 <em>{{ employeeStatus.active }}</em> 人在岗</div>
              <div class="si-desc">
                <span class="si-metric">休假 {{ employeeStatus.vacation }}</span>
                <span class="si-sep">|</span>
                <span class="si-metric">离职 {{ employeeStatus.resigned }}</span>
              </div>
              <div class="si-bar"><div class="si-bar-fill si-bar-blue" :style="{ width: employeeActiveRate + '%' }"></div></div>
            </div>
            <el-icon class="si-arrow"><ArrowRight /></el-icon>
          </div>
        </div>
      </div>
    </section>

    <div class="workflow-summaries">
    <section class="workflow-summary app-panel">
      <h3>{{ workUnitSummary?.scope === 'DEPARTMENT' ? '部门工作单元概览' : '我的工作单元概览' }}</h3>
      <p>仅统计当前工作单元，不代表已审批公开检测记录；员工仅统计当前分配给自己的任务。</p>
      <div v-if="workUnitSummary" class="hero-telemetry">
        <span v-if="workUnitSummary.scope === 'DEPARTMENT'" class="metric-chip">待分配 {{ workUnitSummary.counts.WAITING }}</span>
        <span class="metric-chip">已分配 {{ workUnitSummary.counts.ASSIGNED }}</span>
        <span class="metric-chip">处理中 {{ workUnitSummary.counts.PROCESSING }}</span>
        <span class="metric-chip">已提交待审核 {{ workUnitSummary.counts.SUBMITTED }}</span>
      </div>
      <p v-else>工作单元数据尚未加载成功。</p>
    </section>
    <section class="workflow-summary app-panel">
      <h3>{{ duplicateSummary?.scope === 'DEPARTMENT' ? '部门重复图片复查' : '我的重复图片复查' }}</h3>
      <p>统计已创建的未完成工单；员工仅查看分配给自己的复查工作。</p>
      <div v-if="duplicateSummary" class="hero-telemetry">
        <span v-if="duplicateSummary.scope === 'DEPARTMENT'" class="metric-chip">待分配 {{ duplicateSummary.counts.OPEN }}</span>
        <span class="metric-chip">待对比 {{ duplicateSummary.counts.ASSIGNED }}</span>
        <span class="metric-chip">对比中 {{ duplicateSummary.counts.COMPARING }}</span>
        <span class="metric-chip">待审批 {{ duplicateSummary.counts.PENDING_APPROVAL }}</span>
      </div>
      <p v-else>复查工单数据尚未加载成功。</p>
    </section>
    </div>

    <!-- ── 图表 + 摘要区 ── -->
    <section class="content-grid">
      <!-- 检测趋势 (左侧宽) -->
      <el-card class="chart-card-wide">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">检测趋势</h3>
              <p class="app-panel-subtitle">查看不同时间范围下的检测量和结果结构变化</p>
            </div>
            <el-radio-group v-model="detectionTimeRange" size="small">
              <el-radio-button label="week">近一周</el-radio-button>
              <el-radio-button label="month">近一月</el-radio-button>
              <el-radio-button label="year">近一年</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <div ref="detectionTrendChartRef" class="chart"></div>
      </el-card>

      <!-- 快速状态 (右侧窄) -->
      <el-card class="chart-card-narrow">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">快速状态</h3>
              <p class="app-panel-subtitle">关键指标一览</p>
            </div>
          </div>
        </template>
        <div class="quick-stats">
          <div class="quick-stat-item" @click="router.push('/device-records')">
            <div class="qs-icon qs-icon-blue">
              <el-icon><DataAnalysis /></el-icon>
            </div>
            <div class="qs-content">
              <div class="qs-value">{{ formatNumber(totalDetections) }}</div>
              <div class="qs-label">检测总量</div>
            </div>
          </div>
          <div class="quick-stat-item" @click="router.push('/devices')">
            <div class="qs-icon qs-icon-green">
              <el-icon><Monitor /></el-icon>
            </div>
            <div class="qs-content">
              <div class="qs-value">{{ deviceStatus.online }}/{{ totalDevices }}</div>
              <div class="qs-label">设备在线</div>
            </div>
          </div>
          <div class="quick-stat-item" @click="router.push('/employees')">
            <div class="qs-icon qs-icon-amber">
              <el-icon><User /></el-icon>
            </div>
            <div class="qs-content">
              <div class="qs-value">{{ employeeStatus.active }}/{{ totalEmployees }}</div>
              <div class="qs-label">人员在岗</div>
            </div>
          </div>
          <div class="quick-stat-item">
            <div class="qs-icon qs-icon-red">
              <el-icon><Warning /></el-icon>
            </div>
            <div class="qs-content">
              <div class="qs-value">{{ formatPercent(avgMissRate) }}</div>
              <div class="qs-label">平均漏检率</div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- 地区采集量 (左半) -->
      <el-card class="chart-card-half">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">地区图片采集量</h3>
              <p class="app-panel-subtitle">各城市采集的图片数量和任务数统计</p>
            </div>
          </div>
        </template>
        <div ref="regionChartRef" class="chart"></div>
      </el-card>

      <!-- 检测结果分布 (右半) -->
      <el-card class="chart-card-half">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">检测结果分布</h3>
              <p class="app-panel-subtitle">正常、弯曲、形变、锈蚀、缺失、结构损伤六类结果占比</p>
            </div>
          </div>
        </template>
        <div ref="detectionDistributionChartRef" class="chart"></div>
      </el-card>

      <!-- 设备状态分布 -->
      <el-card class="chart-card-third">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">设备状态分布</h3>
              <p class="app-panel-subtitle">在线、离线、维护与未使用状态汇总</p>
            </div>
          </div>
        </template>
        <div ref="deviceStatusChartRef" class="chart"></div>
      </el-card>

      <!-- 人员状态分布 -->
      <el-card class="chart-card-third">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">人员状态分布</h3>
              <p class="app-panel-subtitle">在岗、休假、离职状态一目了然</p>
            </div>
          </div>
        </template>
        <div ref="employeeStatusChartRef" class="chart"></div>
      </el-card>

      <!-- 设备类型概览 -->
      <el-card class="chart-card-third">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">设备类型概览</h3>
              <p class="app-panel-subtitle">图片采集设备与图像检测设备分布</p>
            </div>
          </div>
        </template>
        <div class="summary-list">
          <div v-for="item in topDevices" :key="item.label" class="summary-item interactive" @click="router.push('/devices')">
            <div class="sm-left">
              <div class="sm-icon" :class="item.label.includes('采集') ? 'sm-icon-cyan' : 'sm-icon-indigo'">
                <el-icon><Monitor /></el-icon>
              </div>
              <div>
                <div class="summary-name">{{ item.label }}</div>
                <div class="summary-meta">{{ item.desc }}</div>
                <div class="summary-meta-second">{{ item.meta }}</div>
              </div>
            </div>
            <div class="sm-value-block">
              <div class="summary-value">{{ item.value }} <small>台</small></div>
              <div class="sm-bar-track">
                <div class="sm-bar-fill" :class="item.label.includes('采集') ? 'sm-bar-cyan' : 'sm-bar-indigo'"
                  :style="{ width: totalDevices ? (item.value / totalDevices * 100) + '%' : '0%' }"></div>
              </div>
            </div>
            <el-icon class="sm-arrow"><ArrowRight /></el-icon>
          </div>
        </div>
      </el-card>

      <!-- 人员类型概览 -->
      <el-card class="chart-card-full">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">人员类型概览</h3>
              <p class="app-panel-subtitle">检测、采集、维修三类岗位分布</p>
            </div>
          </div>
        </template>
        <div class="summary-list summary-list-horizontal">
          <div v-for="(item, idx) in employeeTypeItems" :key="item.label" class="summary-item interactive" @click="router.push('/employees')">
            <div class="sm-left">
              <div class="sm-icon" :class="['sm-icon-green', 'sm-icon-blue', 'sm-icon-amber'][idx]">
                <el-icon><User /></el-icon>
              </div>
              <div>
                <div class="summary-name">{{ item.label }}</div>
                <div class="summary-meta">{{ item.desc }}</div>
              </div>
            </div>
            <div class="sm-value-block">
              <div class="summary-value">{{ item.value }} <small>人</small></div>
              <div class="sm-bar-track">
                <div class="sm-bar-fill" :class="['sm-bar-green', 'sm-bar-blue', 'sm-bar-amber'][idx]"
                  :style="{ width: totalEmployees ? (item.value / totalEmployees * 100) + '%' : '0%' }"></div>
              </div>
            </div>
            <el-icon class="sm-arrow"><ArrowRight /></el-icon>
          </div>
        </div>
      </el-card>

      <!-- 模型使用统计 -->
      <el-card class="chart-card-full">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">模型使用统计</h3>
              <p class="app-panel-subtitle">各检测模型的使用次数、检测图片数和平均漏检率</p>
            </div>
          </div>
        </template>
        <div class="model-stats-grid">
          <div v-for="item in modelStats" :key="item.modelId" class="model-stat-card">
            <div class="model-stat-header">
              <div class="model-stat-icon">
                <el-icon><Setting /></el-icon>
              </div>
              <div class="model-stat-name">{{ item.modelName }}</div>
            </div>
            <div class="model-stat-metrics">
              <div class="model-metric">
                <span class="model-metric-label">使用次数</span>
                <span class="model-metric-value">{{ item.taskCount }} <small>次</small></span>
              </div>
              <div class="model-metric">
                <span class="model-metric-label">检测图片</span>
                <span class="model-metric-value">{{ formatNumber(item.totalImages) }} <small>张</small></span>
              </div>
              <div class="model-metric">
                <span class="model-metric-label">平均漏检率</span>
                <span class="model-metric-value" :class="item.avgMissRate > 5 ? 'text-danger' : 'text-success'">
                  {{ item.avgMissRate.toFixed(2) }}%
                </span>
              </div>
            </div>
            <div class="model-stat-bar">
              <div class="model-stat-bar-fill" :style="{ width: getModelUsagePercent(item.taskCount) + '%' }"></div>
            </div>
          </div>
        </div>
      </el-card>
    </section>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {beijingDateTime} from '@/utils/beijingTime'
import * as echarts from 'echarts'
import {
  User, Monitor, Warning, Search, Setting,
  DataAnalysis, Refresh, WarningFilled, UserFilled, ArrowRight
} from '@element-plus/icons-vue'
import request from '../api/request'
import { getWorkUnitSummary, getDuplicateSummary } from '../api/dashboard'

const router = useRouter()

const pageLoading = ref(true)
const workUnitSummary = ref(null)
const duplicateSummary = ref(null)

async function fetchDuplicateSummary() {
  try {
    const response = await getDuplicateSummary()
    if (response.data?.code !== 200 || !response.data?.data?.counts) throw new Error('复查工单统计异常')
    duplicateSummary.value = response.data.data
    failedSections.value = failedSections.value.filter(item => item !== '复查工单')
  } catch {
    if (!failedSections.value.includes('复查工单')) failedSections.value.push('复查工单')
  }
}

async function fetchWorkUnitSummary() {
  try {
    const response = await getWorkUnitSummary()
    if (response.data?.code !== 200 || !response.data?.data?.counts) throw new Error('工作单元统计异常')
    workUnitSummary.value = response.data.data
    failedSections.value = failedSections.value.filter(item => item !== '工作单元')
  } catch {
    if (!failedSections.value.includes('工作单元')) failedSections.value.push('工作单元')
  }
}
const refreshing = ref(false)
const lastUpdated = ref('')
const failedSections = ref([])
let refreshTimer
let disposed = false

async function dashboardRequest(section, url, config) {
  try {
    const response = await request.get(url, config)
    if (response.data?.code !== 200 || response.data?.data == null) {
      throw new Error('统计接口返回异常')
    }
    failedSections.value = failedSections.value.filter(item => item !== section)
    return response
  } catch (error) {
    if (!failedSections.value.includes(section)) failedSections.value.push(section)
    throw error
  }
}

const totalDetections = ref(0)
const totalEmployees = ref(0)
const totalDevices = ref(0)
const avgMissRate = ref(0)
const detectionTimeRange = ref('month')
const modelStats = ref([])

const deviceStatus = reactive({
  online: 0, offline: 0, maintenance: 0, unused: 0
})

const employeeStatus = reactive({
  active: 0, vacation: 0, resigned: 0,
  detection: 0, collection: 0, maintenance: 0
})

const detectionTrendChartRef = ref(null)
const detectionDistributionChartRef = ref(null)
const deviceStatusChartRef = ref(null)
const employeeStatusChartRef = ref(null)
const regionChartRef = ref(null)

const charts = reactive({
  detectionTrend: null,
  detectionDistribution: null,
  deviceStatus: null,
  employeeStatus: null,
  region: null
})

const DETECTION_CATEGORY_LABELS = {
  Normal: '正常', Bent: '弯曲', Deformed: '形变',
  Rusty: '锈蚀', Missing: '缺失', Compromised: '结构损伤'
}

// ── 计算属性 ──

const onlineRate = computed(() => {
  if (!totalDevices.value) return '0.0'
  return ((deviceStatus.online / totalDevices.value) * 100).toFixed(1)
})

const employeeActiveRate = computed(() => {
  if (!totalEmployees.value) return '0.0'
  return ((employeeStatus.active / totalEmployees.value) * 100).toFixed(1)
})

const maintenanceRate = computed(() => {
  if (!totalDevices.value) return '0.0'
  return ((deviceStatus.maintenance / totalDevices.value) * 100).toFixed(1)
})

const deviceTypeStats = reactive({
  imageCapture: 0,
  imageCaptureInUse: 0,
  detection: 0,
  detectionInUse: 0
})

const topDevices = computed(() => [
  {
    label: '图片采集设备',
    value: deviceTypeStats.imageCapture,
    desc: '负责图像采集与上传',
    meta: `使用中 ${deviceTypeStats.imageCaptureInUse} 台`
  },
  {
    label: '图像检测设备',
    value: deviceTypeStats.detection,
    desc: '负责执行图像检测任务',
    meta: `使用中 ${deviceTypeStats.detectionInUse} 台`
  }
])

const employeeTypeItems = computed(() => [
  { label: '检测人员', value: employeeStatus.detection, desc: '负责检测任务执行' },
  { label: '采集人员', value: employeeStatus.collection, desc: '负责图像采集与上传' },
  { label: '维修人员', value: employeeStatus.maintenance, desc: '负责设备维护和异常处理' }
])

// ── 生命周期 ──

watch(detectionTimeRange, () => updateDetectionTrendChart())

onMounted(async () => {
  await refreshAll()
  if (disposed) return
  await initCharts()
  window.addEventListener('resize', resizeCharts)
  refreshTimer = window.setInterval(() => {
    if (!document.hidden) refreshAll()
  }, 30000)
})

onBeforeUnmount(() => {
  disposed = true
  window.clearInterval(refreshTimer)
  window.removeEventListener('resize', resizeCharts)
  Object.values(charts).forEach(c => c && c.dispose())
})

// ── 数据获取 ──

async function refreshAll() {
  if (refreshing.value || disposed) return
  refreshing.value = true
  try {
    await Promise.all([fetchDashboardStats(), fetchDeviceData(), fetchEmployeeData(), fetchModelStats(), fetchWorkUnitSummary(), fetchDuplicateSummary()])
    if (!disposed) await updateChartData()
    if (!failedSections.value.length && charts.region) lastUpdated.value = beijingDateTime()
  } finally {
    pageLoading.value = false
    refreshing.value = false
  }
}

async function initCharts() {
  await nextTick()
  if (disposed) return
    charts.detectionTrend = echarts.init(detectionTrendChartRef.value)
    charts.detectionDistribution = echarts.init(detectionDistributionChartRef.value)
    charts.deviceStatus = echarts.init(deviceStatusChartRef.value)
    charts.employeeStatus = echarts.init(employeeStatusChartRef.value)
    charts.region = echarts.init(regionChartRef.value)
  await updateChartData()
  if (!failedSections.value.length) lastUpdated.value = beijingDateTime()
}

async function updateChartData() {
  updateDeviceStatusChart()
  updateEmployeeStatusChart()
  await Promise.all([updateDetectionTrendChart(), updateDetectionDistributionChart(), updateRegionChart()])
}

async function fetchDashboardStats() {
  try {
    const res = await dashboardRequest('总览', '/api/dashboard/stats')
    const s = res.data?.data || {}
    totalDetections.value = Number(s.detectionCount || 0)
    totalEmployees.value = Number(s.employeeCount || 0)
    totalDevices.value = Number(s.deviceCount || 0)
    avgMissRate.value = Number(s.avgMissRate || 0)
  } catch { /* 保留旧值，统一显示失败提示。 */ }
}

async function fetchDeviceData() {
  try {
    const res = await dashboardRequest('设备', '/api/devices/stats')
    const stats = res.data?.data || {}
    deviceStatus.online = Number(stats.inUse || 0)
    deviceStatus.offline = Number(stats.offline || 0)
    deviceStatus.maintenance = Number(stats.maintenance || 0)
    deviceStatus.unused = Number(stats.idle || 0)
    totalDevices.value = Number(stats.total || 0)
    deviceTypeStats.imageCapture = Number(stats.imageCapture || 0)
    deviceTypeStats.imageCaptureInUse = Number(stats.imageCaptureInUse || 0)
    deviceTypeStats.detection = Number(stats.detection || 0)
    deviceTypeStats.detectionInUse = Number(stats.detectionInUse || 0)
  } catch { /* 保留旧值。 */ }
}

async function fetchEmployeeData() {
  try {
    const res = await dashboardRequest('人员', '/api/employees/stats')
    const stats = res.data?.data || {}
    employeeStatus.active = Number(stats.active || 0)
    employeeStatus.vacation = Number(stats.vacation || 0)
    employeeStatus.resigned = Number(stats.resigned || 0)
    employeeStatus.detection = Number(stats.detection || 0)
    employeeStatus.collection = Number(stats.collection || 0)
    employeeStatus.maintenance = Number(stats.maintenance || 0)
    totalEmployees.value = Number(stats.total || 0)
  } catch { /* 保留旧值。 */ }
}

async function fetchModelStats() {
  try {
    const res = await dashboardRequest('模型', '/api/dashboard/model-stats')
    modelStats.value = res.data?.data || []
  } catch { /* 保留旧值。 */ }
}

// ── 图表更新 ──

const CHART_COLORS = {
  blue: '#2563eb', green: '#059669', amber: '#d97706',
  violet: '#7c3aed', red: '#dc2626', slate: '#94a3b8',
  purple: '#8b5cf6', cyan: '#0891b2', pale: '#cbd5e1'
}

async function updateDetectionTrendChart() {
  if (!charts.detectionTrend) return
  try {
    const res = await dashboardRequest('检测趋势', '/api/statistics/detection-trend', { params: { timeRange: detectionTimeRange.value } })
    if (disposed) return
    charts.detectionTrend.clear()
    const data = res.data?.data || []
    if (!data.length) { charts.detectionTrend.setOption(buildEmptyOption('暂无趋势数据')); return }

    const labels = data.map(i => i.date)
    const pick = (k) => data.map(i => Number(i[k] || 0))

    charts.detectionTrend.setOption({
      color: [CHART_COLORS.blue, CHART_COLORS.green, CHART_COLORS.amber, CHART_COLORS.violet, CHART_COLORS.red, CHART_COLORS.purple, CHART_COLORS.cyan],
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#fff',
        borderColor: '#e2e8f0',
        textStyle: { color: '#0f172a', fontSize: 13 },
        boxShadow: '0 12px 40px rgba(15,23,42,0.12)'
      },
      legend: { top: 0, textStyle: { color: '#5f728c', fontSize: 12 }, itemGap: 16 },
      grid: { left: 20, right: 18, bottom: 20, top: 48, containLabel: true },
      xAxis: {
        type: 'category', data: labels,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 }
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#f1f5f9' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 }
      },
      series: [
        {
          name: '检测总量', type: 'line', smooth: true, symbolSize: 6,
          lineStyle: { width: 3 }, symbol: 'circle',
          areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1, [
            { offset: 0, color: 'rgba(37,99,235,0.18)' },
            { offset: 1, color: 'rgba(37,99,235,0.0)' }
          ])},
          data: pick('total')
        },
        { name: '正常', type: 'bar', stack: 'result', barMaxWidth: 14, itemStyle: { borderRadius: [4,4,0,0] }, data: pick('normal') },
        { name: '弯曲', type: 'bar', stack: 'result', barMaxWidth: 14, data: pick('bent') },
        { name: '形变', type: 'bar', stack: 'result', barMaxWidth: 14, data: pick('deformed') },
        { name: '锈蚀', type: 'bar', stack: 'result', barMaxWidth: 14, data: pick('rusty') },
        { name: '缺失', type: 'bar', stack: 'result', barMaxWidth: 14, data: pick('missing') },
        { name: '结构损伤', type: 'bar', stack: 'result', barMaxWidth: 14, data: pick('compromised') }
      ]
    })
  } catch { if (!disposed) charts.detectionTrend.setOption(buildEmptyOption('趋势加载失败，请重试'), true) }
}

async function updateDetectionDistributionChart() {
  if (!charts.detectionDistribution) return
  try {
    const res = await dashboardRequest('检测分布', '/api/statistics/detection-distribution')
    if (disposed) return
    charts.detectionDistribution.clear()
    const resultMap = { 正常: 0, 弯曲: 0, 形变: 0, 锈蚀: 0, 缺失: 0, 结构损伤: 0 }
    const data = res.data?.data || []
    if (!data.length) { charts.detectionDistribution.setOption(buildEmptyOption('暂无分布数据')); return }
    data.forEach(item => {
      const label = DETECTION_CATEGORY_LABELS[item.result] || item.result
      if (resultMap[label] !== undefined) resultMap[label] = Number(item.count || 0)
    })
    if (Object.values(resultMap).every(v => v === 0)) { charts.detectionDistribution.setOption(buildEmptyOption('暂无分布数据')); return }

    charts.detectionDistribution.setOption({
      color: [CHART_COLORS.green, CHART_COLORS.amber, CHART_COLORS.violet, CHART_COLORS.red, CHART_COLORS.purple, CHART_COLORS.cyan],
      tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#e2e8f0', textStyle: { color: '#0f172a' } },
      legend: { bottom: 0, textStyle: { color: '#5f728c', fontSize: 12 } },
      series: [{
        type: 'pie', radius: ['50%', '74%'], center: ['50%', '44%'],
        label: { formatter: '{b}\n{d}%', fontSize: 11 },
        itemStyle: { borderRadius: 12, borderColor: '#fff', borderWidth: 3 },
        emphasis: { scaleSize: 8, label: { fontSize: 14, fontWeight: 'bold' } },
        data: [
          { name: '正常', value: resultMap.正常 },
          { name: '弯曲', value: resultMap.弯曲 },
          { name: '形变', value: resultMap.形变 },
          { name: '锈蚀', value: resultMap.锈蚀 },
          { name: '缺失', value: resultMap.缺失 },
          { name: '结构损伤', value: resultMap.结构损伤 }
        ]
      }]
    })
  } catch { if (!disposed) charts.detectionDistribution.setOption(buildEmptyOption('分布加载失败，请重试'), true) }
}

function updateDeviceStatusChart() {
  if (!charts.deviceStatus) return
  charts.deviceStatus.setOption({
    color: [CHART_COLORS.blue, CHART_COLORS.slate, CHART_COLORS.amber, CHART_COLORS.pale],
    tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#e2e8f0', textStyle: { color: '#0f172a' } },
    legend: { bottom: 0, textStyle: { color: '#5f728c', fontSize: 12 } },
    series: [{
      type: 'pie', radius: ['44%', '70%'], center: ['50%', '44%'],
      label: { formatter: '{b}\n{c} 台', fontSize: 11 },
      itemStyle: { borderRadius: 12, borderColor: '#fff', borderWidth: 3 },
      emphasis: { scaleSize: 8 },
      data: [
        { name: '在线', value: deviceStatus.online },
        { name: '离线', value: deviceStatus.offline },
        { name: '维护中', value: deviceStatus.maintenance },
        { name: '未使用', value: deviceStatus.unused }
      ]
    }]
  })
}

function updateEmployeeStatusChart() {
  if (!charts.employeeStatus) return
  charts.employeeStatus.setOption({
    color: [CHART_COLORS.green, CHART_COLORS.amber, CHART_COLORS.slate],
    tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#e2e8f0', textStyle: { color: '#0f172a' } },
    legend: { bottom: 0, textStyle: { color: '#5f728c', fontSize: 12 } },
    series: [{
      type: 'pie', radius: ['44%', '70%'], center: ['50%', '44%'],
      label: { formatter: '{b}\n{d}%', fontSize: 11 },
      itemStyle: { borderRadius: 12, borderColor: '#fff', borderWidth: 3 },
      emphasis: { scaleSize: 8 },
      data: [
        { name: '在岗', value: employeeStatus.active },
        { name: '休假', value: employeeStatus.vacation },
        { name: '离职', value: employeeStatus.resigned }
      ]
    }]
  })
}

async function updateRegionChart() {
  if (!charts.region) return
  try {
    const res = await dashboardRequest('地区采集', '/api/dashboard/region-stats')
    if (disposed) return
    charts.region.clear()
    const data = res.data?.data || []
    if (!data.length) { charts.region.setOption(buildEmptyOption('暂无地区数据')); return }

    const regions = data.map(i => i.region)
    const imageCounts = data.map(i => i.imageCount)
    const taskCounts = data.map(i => i.taskCount)

    charts.region.setOption({
      color: [CHART_COLORS.cyan, CHART_COLORS.blue],
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#fff',
        borderColor: '#e2e8f0',
        textStyle: { color: '#0f172a', fontSize: 13 },
        axisPointer: { type: 'shadow' }
      },
      legend: { top: 0, textStyle: { color: '#5f728c', fontSize: 12 }, itemGap: 16 },
      grid: { left: 20, right: 18, bottom: 20, top: 40, containLabel: true },
      xAxis: {
        type: 'category', data: regions,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#94a3b8', fontSize: 11, rotate: regions.length > 6 ? 30 : 0 }
      },
      yAxis: [
        {
          type: 'value', name: '图片数',
          splitLine: { lineStyle: { color: '#f1f5f9' } },
          axisLabel: { color: '#94a3b8', fontSize: 11 }
        },
        {
          type: 'value', name: '任务数',
          splitLine: { show: false },
          axisLabel: { color: '#94a3b8', fontSize: 11 }
        }
      ],
      series: [
        {
          name: '采集图片数', type: 'bar', barMaxWidth: 32,
          itemStyle: { borderRadius: [6, 6, 0, 0], color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: CHART_COLORS.cyan },
            { offset: 1, color: 'rgba(8,145,178,0.4)' }
          ])},
          data: imageCounts
        },
        {
          name: '采集任务数', type: 'line', yAxisIndex: 1,
          smooth: true, symbolSize: 6, symbol: 'circle',
          lineStyle: { width: 2, color: CHART_COLORS.blue },
          itemStyle: { color: CHART_COLORS.blue },
          data: taskCounts
        }
      ]
    })
  } catch { if (!disposed) charts.region.setOption(buildEmptyOption('地区数据加载失败，请重试'), true) }
}

function buildEmptyOption(text) {
  return {
    title: {
      text, left: 'center', top: 'center',
      textStyle: { color: '#94a3b8', fontSize: 14, fontWeight: 500 }
    }
  }
}

// ── 工具函数 ──

function resizeCharts() { Object.values(charts).forEach(c => c && c.resize()) }

function resetDeviceStatus() {
  deviceStatus.online = deviceStatus.offline = deviceStatus.maintenance = deviceStatus.unused = 0
  deviceTypeStats.imageCapture = deviceTypeStats.imageCaptureInUse = 0
  deviceTypeStats.detection = deviceTypeStats.detectionInUse = 0
}
function resetEmployeeStatus() { employeeStatus.active = employeeStatus.vacation = employeeStatus.resigned = employeeStatus.detection = employeeStatus.collection = employeeStatus.maintenance = 0 }

function formatNumber(v) { return Number(v || 0).toLocaleString('zh-CN') }
function formatPercent(v) { return `${Number(v || 0).toFixed(2)}%` }

function getModelUsagePercent(taskCount) {
  if (!modelStats.value.length) return 0
  const maxCount = Math.max(...modelStats.value.map(m => m.taskCount))
  return maxCount ? (taskCount / maxCount * 100) : 0
}
</script>

<style scoped>
/* ═══════════════════════════════════════════════════════
   Home Dashboard — 仪表板样式
   ═══════════════════════════════════════════════════════ */

.home-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ── Hero + 运行态势 ── */

.hero-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(340px, 0.95fr);
  gap: 18px;
}

.hero-panel, .status-panel {
  padding: 28px;
}

.hero-panel {
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(ellipse at 80% 0%, rgba(37,99,235,0.10), transparent 42%),
    linear-gradient(135deg, rgba(255,255,255,0.96), rgba(239,246,255,0.94));
}

/* Hero Badge */
.hero-title {
  margin: 16px 0 8px;
  font-size: 34px;
  line-height: 1.16;
  font-weight: 800;
  letter-spacing: -0.035em;
  color: var(--app-text);
}

.hero-text {
  max-width: 660px;
  margin: 0;
  color: var(--app-text-secondary);
  line-height: 1.75;
  font-size: 14px;
}

.hero-telemetry {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}

.hero-actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
}

/* Hero Highlights */
.hero-highlights {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 28px;
}

.highlight-card {
  position: relative;
  overflow: hidden;
  padding: 18px;
  border-radius: 14px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(248, 250, 252, 0.90));
  border: 1px solid rgba(37, 99, 235, 0.10);
  transition: all var(--app-transition-fast);
  box-shadow: var(--app-shadow-xs);
}

.highlight-card::after {
  content: "";
  position: absolute;
  right: -28px;
  top: -28px;
  width: 84px;
  height: 84px;
  border-radius: 999px;
  background: var(--app-primary-soft);
  opacity: 0.72;
}

.highlight-card:hover {
  border-color: rgba(37, 99, 235, 0.18);
  box-shadow: var(--app-shadow-command);
  transform: translateY(-2px);
}

.hl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.hl-icon {
  width: 32px; height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 16px;
}
.hl-icon-blue   { color: var(--app-primary); background: var(--app-primary-soft); }
.hl-icon-green  { color: var(--app-success); background: var(--app-success-soft); }
.hl-icon-amber  { color: var(--app-warning); background: var(--app-warning-soft); }

.hl-trend {
  font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: 999px;
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
}
.hl-trend.up { color: var(--app-success); }

.hl-value {
  display: block;
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--app-text);
  line-height: 1.1;
}
.hl-value small { font-size: 18px; font-weight: 600; color: var(--app-text-secondary); }

.hl-label {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--app-text-muted);
}

/* ── 运行态势 ── */

.status-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.status-list {
  display: grid;
  gap: 12px;
  margin-top: 18px;
}

.status-item {
  display: flex;
  gap: 14px;
  padding: 14px 16px;
  border-radius: 14px;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.88), rgba(248, 250, 252, 0.82));
  border: 1px solid rgba(15, 23, 42, 0.05);
  transition: all var(--app-transition-fast);
}
.status-item.interactive {
  cursor: pointer;
  align-items: center;
}
.status-item.interactive:hover {
  border-color: rgba(37, 99, 235, 0.14);
  background: var(--app-surface-strong);
  transform: translateX(2px);
  box-shadow: var(--app-shadow-sm);
}
.status-item.interactive:hover .si-arrow {
  opacity: 1;
  transform: translateX(0);
}
.si-arrow {
  flex-shrink: 0;
  color: var(--app-text-muted);
  opacity: 0;
  transform: translateX(-4px);
  transition: all var(--app-transition-fast);
}

.si-indicator {
  width: 36px; height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  font-size: 16px;
}
.si-online   { color: var(--app-success); background: var(--app-success-soft); }
.si-maintain { color: var(--app-warning); background: var(--app-warning-soft); }
.si-schedule { color: var(--app-primary); background: var(--app-primary-soft); }

.si-body { flex: 1; min-width: 0; }

.si-title {
  font-weight: 700;
  color: var(--app-text);
  font-size: 14px;
}
.si-title em {
  font-style: normal;
  font-weight: 800;
  font-size: 16px;
  margin: 0 2px;
}

.si-desc {
  margin-top: 3px;
  font-size: 12px;
  color: var(--app-text-muted);
}
.si-metric { color: var(--app-text-secondary); }
.si-sep { margin: 0 6px; color: var(--app-border-strong); }

.si-bar {
  height: 4px;
  border-radius: 2px;
  background: var(--app-border);
  margin-top: 8px;
  overflow: hidden;
}
.si-bar-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--app-success);
  transition: width 0.6s var(--app-ease-spring);
}
.si-bar-warn { background: var(--app-warning); }
.si-bar-blue { background: var(--app-primary); }

/* ── 图表面板 ── */

.content-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 18px;
}

.chart-card-full   { grid-column: span 12; }
.chart-card-wide   { grid-column: span 8; }
.chart-card-narrow { grid-column: span 4; }
.chart-card-half   { grid-column: span 6; }
.chart-card-third  { grid-column: span 4; }

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.chart {
  width: 100%;
  height: 320px;
}

/* ── 摘要列表 ── */

.summary-list {
  display: grid;
  gap: 12px;
  min-height: 320px;
  align-content: start;
}

.summary-list-horizontal {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  min-height: auto;
}

/* ── 模型统计 ── */

.model-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.model-stat-card {
  padding: 20px;
  border-radius: 14px;
  background: var(--app-surface-muted);
  border: 1px solid transparent;
  transition: all var(--app-transition-fast);
}

.model-stat-card:hover {
  border-color: var(--app-border);
  background: var(--app-surface-strong);
  box-shadow: var(--app-shadow-sm);
}

.model-stat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.model-stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 18px;
  color: var(--app-primary);
  background: var(--app-primary-soft);
}

.model-stat-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--app-text);
}

.model-stat-metrics {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
}

.model-metric {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.model-metric-label {
  font-size: 12px;
  color: var(--app-text-muted);
}

.model-metric-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--app-text);
}

.model-metric-value small {
  font-size: 12px;
  font-weight: 500;
  color: var(--app-text-muted);
}

.text-danger { color: var(--app-danger); }
.text-success { color: var(--app-success); }

.model-stat-bar {
  height: 6px;
  border-radius: 3px;
  background: var(--app-border);
  overflow: hidden;
}

.model-stat-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--app-primary), var(--app-primary-light));
  transition: width 0.6s var(--app-ease-spring);
}

/* ── 快速状态 ── */

.quick-stats {
  display: grid;
  gap: 14px;
  min-height: 320px;
  align-content: start;
}

.quick-stat-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border-radius: 14px;
  background: linear-gradient(135deg, #fff, #f8fbff);
  border: 1px solid rgba(37, 99, 235, 0.08);
  cursor: pointer;
  transition: all var(--app-transition-fast);
}

.quick-stat-item:hover {
  border-color: rgba(37, 99, 235, 0.18);
  background: var(--app-surface-strong);
  transform: translateX(2px);
  box-shadow: var(--app-shadow-sm);
}

.qs-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 20px;
  flex-shrink: 0;
}

.qs-icon-blue  { color: var(--app-primary); background: var(--app-primary-soft); }
.qs-icon-green { color: var(--app-success); background: var(--app-success-soft); }
.qs-icon-amber { color: var(--app-warning); background: var(--app-warning-soft); }
.qs-icon-red   { color: var(--app-danger); background: var(--app-danger-soft); }

.qs-content {
  flex: 1;
  min-width: 0;
}

.qs-value {
  font-size: 22px;
  font-weight: 800;
  color: var(--app-text);
  line-height: 1.2;
}

.qs-label {
  margin-top: 2px;
  font-size: 12px;
  color: var(--app-text-muted);
}

.summary-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px;
  border-radius: 14px;
  background: var(--app-surface-muted);
  border: 1px solid transparent;
  transition: all var(--app-transition-fast);
}
.summary-item.interactive {
  cursor: pointer;
}
.summary-item.interactive:hover {
  border-color: var(--app-border);
  background: var(--app-surface-strong);
  transform: translateX(2px);
}
.summary-item.interactive:hover .sm-arrow {
  opacity: 1;
  transform: translateX(0);
}
.sm-arrow {
  flex-shrink: 0;
  color: var(--app-text-muted);
  opacity: 0;
  transform: translateX(-4px);
  transition: all var(--app-transition-fast);
}

.sm-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.sm-icon {
  width: 40px; height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  font-size: 18px;
  flex-shrink: 0;
}
.sm-icon-cyan   { color: #0891b2; background: rgba(8,145,178,0.1); }
.sm-icon-indigo { color: #4f46e5; background: rgba(79,70,229,0.1); }
.sm-icon-green  { color: #059669; background: rgba(5,150,105,0.1); }
.sm-icon-blue   { color: #2563eb; background: rgba(37,99,235,0.1); }
.sm-icon-amber  { color: #d97706; background: rgba(217,119,6,0.1); }

.summary-name {
  font-weight: 700;
  font-size: 14px;
  color: var(--app-text);
}

.summary-meta {
  margin-top: 2px;
  color: var(--app-text-secondary);
  font-size: 12px;
}

.summary-meta-second {
  margin-top: 2px;
  color: var(--app-text-muted);
  font-size: 11px;
}

.sm-value-block {
  text-align: right;
  flex-shrink: 0;
  min-width: 80px;
}

.summary-value {
  font-size: 22px;
  font-weight: 800;
  color: var(--app-text);
  line-height: 1.1;
}
.summary-value small {
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text-muted);
}

.sm-bar-track {
  height: 4px;
  border-radius: 2px;
  background: var(--app-border);
  margin-top: 6px;
  overflow: hidden;
  min-width: 60px;
}
.sm-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.6s var(--app-ease-spring);
}
.sm-bar-cyan   { background: #0891b2; }
.sm-bar-indigo { background: #4f46e5; }
.sm-bar-green  { background: #059669; }
.sm-bar-blue   { background: #2563eb; }
.sm-bar-amber  { background: #d97706; }

/* ── 响应式 ── */

@media (max-width: 1200px) {
  .hero-grid {
    grid-template-columns: 1fr 1fr;
  }
  .chart-card-full,
  .chart-card-wide,
  .chart-card-narrow,
  .chart-card-half,
  .chart-card-third {
    grid-column: span 12;
  }
  .summary-list-horizontal {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .hero-grid,
  .hero-highlights {
    grid-template-columns: 1fr;
  }
  .hero-panel, .status-panel {
    padding: 20px;
  }
  .hero-title { font-size: 24px; }
  .hero-actions { flex-direction: column; }
  .chart { height: 260px; }
  .hl-value { font-size: 26px; }
}
.dashboard-refresh-note { margin-bottom: 16px; font-size: 11px; color: var(--app-text-muted); }
.workflow-summaries { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 20px 0; }
.workflow-summary { padding: 20px; min-width: 0; }
.workflow-summary h3 { font-size: 14px; margin: 0 0 6px; }
.workflow-summary p { font-size: 12px; line-height: 1.7; color: var(--app-text-muted); }
@media (max-width: 900px) { .workflow-summaries { grid-template-columns: 1fr; } }
</style>
