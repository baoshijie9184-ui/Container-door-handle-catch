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
    <PageHero :title="userStore.role === 'SUPERVISOR' ? '企业质量工作台' : '我的检测工作台'" icon="DataAnalysis" :description="userStore.role === 'SUPERVISOR' ? '查看企业检测与质量情况，安排复核、跟进异常和设备维护。' : '查看本人及分派任务，跟进检测结果、质检处理和工作记录。'">
      <template #actions>
          <el-button type="primary" @click="router.push('/inspection/workbench')">
            <el-icon style="margin-right:6px"><Search /></el-icon>
            开始图像检测
          </el-button>
          <el-button plain @click="router.push('/models')">
            <el-icon style="margin-right:6px"><Setting /></el-icon>
            管理检测模型
          </el-button>
          <el-button plain @click="router.push('/agent/chat')">向 AI 助手提问 <el-icon style="margin-left:4px"><ArrowRight /></el-icon></el-button>
      </template>
    </PageHero>
    <div role="status" class="dashboard-refresh-note">
      <span>{{ refreshing ? '正在刷新…' : '每 30 秒自动刷新（后台页面暂停）' }}</span>
      <span v-if="lastUpdated"> · 最近全部更新成功：{{ lastUpdated }} UTC+8</span>
      <el-alert v-if="failedSections.length" type="warning" :closable="false"
        :title="`加载失败：${failedSections.join('、')}。对应区域可能保留上次数据；未读取或缺失的指标显示 —，请刷新核对。`" />
    </div>
    <p class="dashboard-data-note">任务统计按当前账号可访问范围汇总；历史累计沿用历史登记数值，设备与人员为全部登记资料。“—”表示尚未读取、字段缺失或无法计算，不代表零。</p>
    <HistoricalDetectionOverview v-if="canViewHistoricalSummary && historicalSummary" :summary="historicalSummary" />
    <section class="quality-overview" aria-labelledby="quality-overview-title" :aria-busy="refreshing">
      <header><div><h2 id="quality-overview-title">{{ userStore.role === 'SUPERVISOR' ? '企业质量待办' : '我的质量待办' }}</h2><p>按当前账号可访问任务统计 · 当前状态 · 时间 UTC+8</p></div><router-link to="/quality/queue"><AppIcon name="ArrowRight" :size="16" />全部质检任务</router-link></header>
      <div class="quality-overview-grid">
        <router-link v-for="metric in qualityMetrics" :key="metric.key" :to="{path:'/quality/queue',query:{queue:metric.queue}}" :data-tone="metric.tone"><span class="quality-overview-icon"><AppIcon :name="metric.icon" :size="20" /></span><span><strong>{{ qualityWorkload ? formatNumber(qualityWorkload[metric.key]) : '—' }}</strong><small>{{ metric.label }}</small></span><AppIcon name="ArrowRight" :size="15" /></router-link>
      </div>
      <p v-if="!qualityWorkload" class="quality-overview-note">{{ failedSections.includes('质量待办') ? '质量待办暂不可读取，请刷新核对；缺失值不代表零。' : '正在读取质量待办…' }}</p>
      <p v-else class="quality-overview-note">{{ failedSections.includes('质量待办') ? '本次刷新失败，以上保留上次数据，请刷新核对。' : '各类待办可能交叉，不能直接相加作为任务总数。' }}</p>
    </section>
    <!-- ── 顶部 Hero + 运行态势 ── -->
    <section class="hero-grid" aria-label="任务与资源概览">
      <div class="hero-panel app-panel command-panel">
        <h2 class="app-panel-title">任务与资源</h2>
        <div class="hero-telemetry">
          <span class="metric-chip">使用中设备 {{ formatNumber(deviceStatus.inUse) }} 台</span>
          <span class="metric-chip">在岗人员 {{ formatNumber(employeeStatus.active) }} 人</span>
          <span class="metric-chip">登记设备 {{ formatNumber(totalDevices) }} 台</span>
        </div>

        <div class="hero-highlights">
          <router-link class="highlight-card hl-primary" title="打开检测记录，统计范围以列表查询为准" to="/inspection/history">
            <div class="hl-header">
              <div class="hl-icon hl-icon-blue">
                <el-icon><DataAnalysis /></el-icon>
              </div>
              <span class="hl-trend">累计</span>
            </div>
            <strong class="hl-value">{{ formatNumber(totalDetections) }}</strong>
            <span class="hl-label">累计完成检测任务数（含部分失败）</span>
          </router-link>
          <router-link class="highlight-card hl-success" title="打开设备列表核对登记状态" to="/devices">
            <div class="hl-header">
              <div class="hl-icon hl-icon-green">
                <el-icon><Monitor /></el-icon>
              </div>
              <span class="hl-trend">{{ formatNumber(deviceStatus.inUse) }} 使用中</span>
            </div>
            <strong class="hl-value">{{ inUseRate ?? '—' }}<small v-if="inUseRate !== null">%</small></strong>
            <span class="hl-label">登记设备使用率</span>
          </router-link>
          <router-link class="highlight-card hl-neutral" title="打开人员列表核对在岗状态" to="/employees">
            <div class="hl-header">
              <div class="hl-icon hl-icon-blue">
                <el-icon><User /></el-icon>
              </div>
              <span class="hl-trend">{{ formatNumber(employeeStatus.active) }} 在岗</span>
            </div>
            <strong class="hl-value">{{ employeeActiveRate ?? '—' }}<small v-if="employeeActiveRate !== null">%</small></strong>
            <span class="hl-label">人员在岗率</span>
          </router-link>
        </div>
      </div>

      <div class="status-panel app-panel">
        <div class="status-header">
          <div>
            <h3 class="app-panel-title">运行态势</h3>
            <p class="app-panel-subtitle">设备与人员登记状态，不表示实时在线心跳</p>
          </div>
          <el-button text size="small" :loading="refreshing" @click="refreshAll">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>

        <div class="status-list">
          <router-link class="status-item interactive" to="/devices">
            <div class="si-indicator si-online">
              <el-icon><Monitor /></el-icon>
            </div>
            <div class="si-body">
              <div class="si-title">设备使用中 <em>{{ formatNumber(deviceStatus.inUse) }}</em> 台</div>
              <div class="si-desc">
                <span class="si-metric">离线 {{ formatNumber(deviceStatus.offline) }}</span>
                <span class="si-sep">|</span>
                <span class="si-metric">未使用 {{ formatNumber(deviceStatus.unused) }}</span>
              </div>
              <div v-if="inUseRate !== null" class="si-bar" aria-hidden="true"><div class="si-bar-fill" :style="{ width: inUseRate + '%' }"></div></div>
            </div>
            <el-icon class="si-arrow"><ArrowRight /></el-icon>
          </router-link>
          <router-link class="status-item interactive" to="/devices">
            <div class="si-indicator si-maintain">
              <el-icon><WarningFilled /></el-icon>
            </div>
            <div class="si-body">
              <div class="si-title">维护关注 <em>{{ formatNumber(deviceStatus.maintenance) }}</em> 台</div>
              <div class="si-desc">设备维护中，需安排检修</div>
              <div v-if="maintenanceRate !== null" class="si-bar" aria-hidden="true"><div class="si-bar-fill si-bar-warn" :style="{ width: maintenanceRate + '%' }"></div></div>
            </div>
            <el-icon class="si-arrow"><ArrowRight /></el-icon>
          </router-link>
          <router-link class="status-item interactive" to="/employees">
            <div class="si-indicator si-schedule">
              <el-icon><UserFilled /></el-icon>
            </div>
            <div class="si-body">
              <div class="si-title">人员状态 <em>{{ formatNumber(employeeStatus.active) }}</em> 人在岗</div>
              <div class="si-desc">
                <span class="si-metric">休假 {{ formatNumber(employeeStatus.vacation) }}</span>
                <span class="si-sep">|</span>
                <span class="si-metric">离职 {{ formatNumber(employeeStatus.resigned) }}</span>
              </div>
              <div v-if="employeeActiveRate !== null" class="si-bar" aria-hidden="true"><div class="si-bar-fill si-bar-blue" :style="{ width: employeeActiveRate + '%' }"></div></div>
            </div>
            <el-icon class="si-arrow"><ArrowRight /></el-icon>
          </router-link>
        </div>
      </div>
    </section>

    <div class="workflow-summaries">
    <section class="workflow-summary app-panel">
      <h3>{{ workUnitSummary?.scope === 'DEPARTMENT' ? '部门工作单元概览' : '我的工作单元概览' }}</h3>
      <p>仅统计当前工作单元，不代表已审批公开检测记录；员工仅统计当前分配给自己的任务。</p>
      <div v-if="workUnitSummary" class="hero-telemetry">
        <span v-if="workUnitSummary.scope === 'DEPARTMENT'" class="metric-chip">待分配 {{ formatNumber(workUnitSummary.counts.WAITING) }}</span>
        <span class="metric-chip">已分配 {{ formatNumber(workUnitSummary.counts.ASSIGNED) }}</span>
        <span class="metric-chip">处理中 {{ formatNumber(workUnitSummary.counts.PROCESSING) }}</span>
        <span class="metric-chip">已提交待审核 {{ formatNumber(workUnitSummary.counts.SUBMITTED) }}</span>
      </div>
      <p v-else>工作单元数据尚未加载成功。</p>
      <p v-if="workUnitSummary && failedSections.includes('工作单元')" role="status">本次刷新失败，保留上次统计，请刷新核对。</p>
    </section>
    <section class="workflow-summary app-panel">
      <h3>{{ duplicateSummary?.scope === 'DEPARTMENT' ? '部门重复图片复查' : '我的重复图片复查' }}</h3>
      <p>统计已创建的未完成工单；员工仅查看分配给自己的复查工作。</p>
      <div v-if="duplicateSummary" class="hero-telemetry">
        <span v-if="duplicateSummary.scope === 'DEPARTMENT'" class="metric-chip">待分配 {{ formatNumber(duplicateSummary.counts.OPEN) }}</span>
        <span class="metric-chip">待对比 {{ formatNumber(duplicateSummary.counts.ASSIGNED) }}</span>
        <span class="metric-chip">对比中 {{ formatNumber(duplicateSummary.counts.COMPARING) }}</span>
        <span class="metric-chip">待审批 {{ formatNumber(duplicateSummary.counts.PENDING_APPROVAL) }}</span>
      </div>
      <p v-else>复查工单数据尚未加载成功。</p>
      <p v-if="duplicateSummary && failedSections.includes('复查工单')" role="status">本次刷新失败，保留上次统计，请刷新核对。</p>
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
              <p class="app-panel-subtitle">{{ trendScopeLabel }} · 按任务创建日期分组，仅含完成及部分失败任务</p>
            </div>
            <el-radio-group v-model="detectionTimeRange" size="small" aria-label="检测趋势统计范围">
              <el-radio-button label="week">近 7 天</el-radio-button>
              <el-radio-button label="month">近 12 个月</el-radio-button>
              <el-radio-button label="year">全部年份</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <div ref="detectionTrendChartRef" class="chart" role="img" :aria-label="`${trendScopeLabel}检测趋势：左轴任务图片数，右轴各类目标数`" :aria-busy="trendLoading"></div>
        <p class="dashboard-data-note">图片数与目标数单位不同，一张图片可以有多个目标；此时间范围仅作用于本图。</p>
        <p v-if="detectionTimeRange==='month'" class="dashboard-data-note">月份标签沿用原统计记录，尚未包含年份；跨年明细请在检测历史核对。</p>
        <ChartDataDetails title="查看趋势数据" :columns="trendColumns" :rows="chartReadouts.trend.rows" :scope="chartReadouts.trend.scope || trendScopeLabel" :loaded="chartReadouts.trend.loaded" :loading="trendLoading" :read-error="failedSections.includes('检测趋势')?'趋势统计暂不可读取。':''" />
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
          <router-link class="quick-stat-item" to="/inspection/history">
            <div class="qs-icon qs-icon-blue">
              <el-icon><DataAnalysis /></el-icon>
            </div>
            <div class="qs-content">
              <div class="qs-value">{{ formatNumber(totalDetections) }}</div>
              <div class="qs-label">累计完成任务（含部分失败）</div>
            </div>
          </router-link>
          <router-link class="quick-stat-item" to="/devices">
            <div class="qs-icon qs-icon-green">
              <el-icon><Monitor /></el-icon>
            </div>
            <div class="qs-content">
              <div class="qs-value">{{ formatNumber(deviceStatus.inUse) }}/{{ formatNumber(totalDevices) }}</div>
              <div class="qs-label">使用中 / 登记设备</div>
            </div>
          </router-link>
          <router-link class="quick-stat-item" to="/employees">
            <div class="qs-icon qs-icon-blue">
              <el-icon><User /></el-icon>
            </div>
            <div class="qs-content">
              <div class="qs-value">{{ formatNumber(employeeStatus.active) }}/{{ formatNumber(totalEmployees) }}</div>
              <div class="qs-label">人员在岗</div>
            </div>
          </router-link>
          <router-link class="quick-stat-item" to="/employees">
            <div class="qs-icon qs-icon-slate">
              <el-icon><User /></el-icon>
            </div>
            <div class="qs-content">
              <div class="qs-value">{{ formatNumber(totalEmployees) }}</div>
              <div class="qs-label">登记人员总数</div>
            </div>
          </router-link>
        </div>
      </el-card>

      <!-- 地区采集量 (左半) -->
      <el-card class="chart-card-half">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">地区图片采集量</h3>
              <p class="app-panel-subtitle">当前账号可访问的累计完成任务（含部分失败），按登记地区分组</p>
            </div>
          </div>
        </template>
        <div ref="regionChartRef" class="chart" role="img" aria-label="登记地区的累计任务图片数与任务数"></div>
        <ChartDataDetails title="查看地区数据" :columns="regionColumns" :rows="chartReadouts.region.rows" scope="当前账号可访问的累计完成任务（含部分失败），按登记地区分组" :loaded="chartReadouts.region.loaded" :loading="refreshing" :read-error="failedSections.includes('地区采集')?'地区统计暂不可读取。':''" />
      </el-card>

      <!-- 检测结果分布 (右半) -->
      <el-card class="chart-card-half">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">检测结果分布</h3>
              <p class="app-panel-subtitle">当前账号可访问的累计完成任务（含部分失败），六类检测目标占比</p>
            </div>
          </div>
        </template>
        <div ref="detectionDistributionChartRef" class="chart" role="img" aria-label="六类检测目标累计分布，不代表人工复核结果"></div>
        <p class="dashboard-data-note">按检测目标计数，非图片数或人工复核结论。</p>
        <ChartDataDetails title="查看分类目标数" :columns="targetColumns" :rows="chartReadouts.distribution.rows" scope="当前账号可访问的累计完成任务（含部分失败），按检测目标计数" :loaded="chartReadouts.distribution.loaded" :loading="refreshing" :read-error="failedSections.includes('检测分布')?'分类统计暂不可读取。':''" />
      </el-card>

      <!-- 设备状态分布 -->
      <el-card class="chart-card-third">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">设备状态分布</h3>
              <p class="app-panel-subtitle">全部登记设备的当前状态：使用中、离线、维护与未使用</p>
            </div>
          </div>
        </template>
        <div ref="deviceStatusChartRef" class="chart" role="img" aria-label="登记设备的当前状态分布"></div>
        <ChartDataDetails title="查看设备状态数" :columns="deviceColumns" :rows="deviceStatusRows" scope="全部登记设备的当前业务状态，不表示实时在线心跳" :loaded="deviceStatusRows.every(row=>row.count!==null)" :loading="refreshing" :read-error="failedSections.includes('设备')?'设备统计暂不可读取。':''" />
      </el-card>

      <!-- 人员状态分布 -->
      <el-card class="chart-card-third">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">人员状态分布</h3>
              <p class="app-panel-subtitle">全部登记人员的当前状态：在岗、休假与离职</p>
            </div>
          </div>
        </template>
        <div ref="employeeStatusChartRef" class="chart" role="img" aria-label="登记人员的当前状态分布"></div>
        <ChartDataDetails title="查看人员状态数" :columns="employeeColumns" :rows="employeeStatusRows" scope="全部登记人员的当前在岗状态" :loaded="employeeStatusRows.every(row=>row.count!==null)" :loading="refreshing" :read-error="failedSections.includes('人员')?'人员统计暂不可读取。':''" />
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
          <router-link v-for="item in topDevices" :key="item.label" class="summary-item interactive" to="/devices">
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
              <div class="summary-value">{{ formatNumber(item.value) }} <small>台</small></div>
              <div v-if="ratio(item.value, totalDevices) !== null" class="sm-bar-track" aria-hidden="true">
                <div class="sm-bar-fill" :class="item.label.includes('采集') ? 'sm-bar-cyan' : 'sm-bar-indigo'"
                  :style="{ width: ratio(item.value, totalDevices) + '%' }"></div>
              </div>
            </div>
            <el-icon class="sm-arrow"><ArrowRight /></el-icon>
          </router-link>
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
          <router-link v-for="(item, idx) in employeeTypeItems" :key="item.label" class="summary-item interactive" to="/employees">
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
              <div class="summary-value">{{ formatNumber(item.value) }} <small>人</small></div>
              <div v-if="ratio(item.value, totalEmployees) !== null" class="sm-bar-track" aria-hidden="true">
                <div class="sm-bar-fill" :class="['sm-bar-green', 'sm-bar-blue', 'sm-bar-amber'][idx]"
                  :style="{ width: ratio(item.value, totalEmployees) + '%' }"></div>
              </div>
            </div>
            <el-icon class="sm-arrow"><ArrowRight /></el-icon>
          </router-link>
        </div>
      </el-card>

      <!-- 模型使用统计 -->
      <el-card class="chart-card-full">
        <template #header>
          <div class="panel-header">
            <div>
              <h3 class="app-panel-title">模型使用统计</h3>
              <p class="app-panel-subtitle">当前账号可访问的累计完成任务（含部分失败），按检测模型汇总</p>
            </div>
          </div>
        </template>
        <CollectionEmptyState v-if="!modelStats.length" :loading="modelStatsLoading" :error="failedSections.includes('模型') ? '模型使用统计暂不可读取，请重新读取。' : ''" empty-title="暂无模型使用记录" empty-description="完成检测任务后，在这里查看模型的累计使用情况。" @retry="fetchModelStats" />
        <p v-else-if="failedSections.includes('模型')" class="dashboard-data-note" role="status">本次读取失败，保留上次模型统计，请刷新核对。</p>
        <div v-if="modelStats.length" class="model-stats-grid">
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
                <span class="model-metric-value">{{ formatNumber(item.taskCount) }} <small>次</small></span>
              </div>
              <div class="model-metric">
                <span class="model-metric-label">检测图片</span>
                <span class="model-metric-value">{{ formatNumber(item.totalImages) }} <small>张</small></span>
              </div>
            </div>
            <div v-if="getModelUsagePercent(item.taskCount) !== null" class="model-stat-bar" aria-hidden="true">
              <div class="model-stat-bar-fill" :style="{ width: getModelUsagePercent(item.taskCount) + '%' }"></div>
            </div>
          </div>
        </div>
        <details class="dashboard-source-note">
          <summary><AppIcon name="Warning" :size="15" />漏检率统计口径待核对</summary>
          <p>历史任务的漏检率字段存在不同算法和单位，且接口可能将缺失值返回为零。这里保留原始字段供核对，不换算百分比，也不作为质量指标；人工结论请查看质检记录。</p>
          <dl><dt>总览原始均值</dt><dd>{{ rawStatistic(avgMissRate) }}</dd><template v-for="item in modelStats" :key="item.modelId"><dt>{{ item.modelName }}</dt><dd>{{ rawStatistic(item.avgMissRate) }}</dd></template></dl>
        </details>
      </el-card>
    </section>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import {beijingDateTime} from '@/utils/beijingTime'
import { knownCount } from '@/utils/countPresentation'
import CollectionEmptyState from '@/components/CollectionEmptyState.vue'
import ChartDataDetails from '@/components/ChartDataDetails.vue'
import HistoricalDetectionOverview from '@/components/HistoricalDetectionOverview.vue'
import * as echarts from 'echarts'
import {
  User, Monitor, Search, Setting,
  DataAnalysis, Refresh, WarningFilled, UserFilled, ArrowRight
} from '@element-plus/icons-vue'
import request from '../api/request'
import { getWorkUnitSummary, getDuplicateSummary } from '../api/dashboard'

const router = useRouter()
const userStore = useUserStore()

const pageLoading = ref(true)
const workUnitSummary = ref(null)
const duplicateSummary = ref(null)
const qualityWorkload = ref(null)
const qualityMetrics = [
  { key:'pendingReviewCount',label:'待复核',queue:'PENDING_REVIEW',icon:'Search',tone:'primary' },
  { key:'pendingDispositionCount',label:'待处置',queue:'PENDING_DISPOSITION',icon:'CircleCheck',tone:'warning' },
  { key:'reworkRequiredCount',label:'待返工',queue:'REWORK_REQUIRED',icon:'Edit',tone:'warning' },
  { key:'recheckRequiredCount',label:'需复检',queue:'RECHECK_REQUIRED',icon:'Refresh',tone:'warning' },
  { key:'holdCount',label:'暂挂',queue:'HOLD',icon:'Clock',tone:'warning' },
  { key:'failedCount',label:'检测异常',queue:'FAILED',icon:'Warning',tone:'danger' }
]

async function fetchQualityWorkload() {
  try {
    const response = await dashboardRequest('质量待办', '/api/dashboard/quality-workload')
    const counts = response.data?.data
    if (!counts || qualityMetrics.some(metric => !Number.isSafeInteger(counts[metric.key]) || counts[metric.key] < 0)) throw new Error('质量待办统计不完整')
    if (!disposed) qualityWorkload.value = Object.fromEntries(qualityMetrics.map(metric => [metric.key, counts[metric.key]]))
  } catch {
    if (!disposed && !failedSections.value.includes('质量待办')) failedSections.value.push('质量待办')
  }
}

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

function markSectionFailed(section) {
  if (!failedSections.value.includes(section)) failedSections.value.push(section)
}

const totalDetections = ref(null)
const historicalSummary = ref(null)
const canViewHistoricalSummary = computed(() => userStore.isAuthenticated && ['SUPERVISOR', 'ADMIN'].includes(userStore.role))
const historicalAccountScope = () => JSON.stringify([userStore.identity?.userId, userStore.username, userStore.role, userStore.isAuthenticated])
watch(historicalAccountScope, () => { historicalSummary.value = null }, { flush: 'sync' })
const totalEmployees = ref(null)
const totalDevices = ref(null)
const avgMissRate = ref(null)
const detectionTimeRange = ref('month')
const modelStats = ref([])
const modelStatsLoading = ref(false)
const trendLoading = ref(false)
const trendScopeLabel = computed(() => ({ week: '近 7 天，按日', month: '近 12 个月，按月', year: '全部年份，按年' })[detectionTimeRange.value])
let trendRequestGeneration = 0
let renderedTrendRange = null

const deviceStatus = reactive({
  inUse: null, offline: null, maintenance: null, unused: null
})

// Reading alternatives use the same validated values as the charts, without another request.
const chartReadouts=reactive({trend:{rows:[],loaded:false,scope:''},region:{rows:[],loaded:false},distribution:{rows:[],loaded:false}})
const trendColumns=[{key:'period',label:'统计分组'},...Object.entries({total:'图片数（张）',normal:'正常目标（个）',bent:'弯曲目标（个）',deformed:'形变目标（个）',rusty:'锈蚀目标（个）',missing:'缺失目标（个）',compromised:'结构损伤目标（个）'}).map(([key,label])=>({key,label,numeric:true}))]
const regionColumns=[{key:'label',label:'登记地区'},{key:'images',label:'图片数（张）',numeric:true},{key:'tasks',label:'任务数（个）',numeric:true}]
const targetColumns=[{key:'label',label:'检测类别'},{key:'count',label:'目标数（个）',numeric:true}]
const deviceColumns=[{key:'label',label:'设备业务状态'},{key:'count',label:'设备数（台）',numeric:true}]
const employeeColumns=[{key:'label',label:'人员状态'},{key:'count',label:'人数（人）',numeric:true}]
const deviceStatusRows=computed(()=>Object.entries({inUse:'使用中',offline:'离线',maintenance:'维护中',unused:'未使用'}).map(([key,label])=>({label,count:deviceStatus[key]})))

const employeeStatus = reactive({
  active: null, vacation: null, resigned: null,
  detection: null, collection: null, maintenance: null
})
const employeeStatusRows=computed(()=>Object.entries({active:'在岗',vacation:'休假',resigned:'离职'}).map(([key,label])=>({label,count:employeeStatus[key]})))

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

const chartMotionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
function chartMotionOptions() {
  return { animation: !chartMotionPreference.matches, animationDuration: 200, animationDurationUpdate: 200 }
}
function updateChartMotion() {
  Object.values(charts).forEach(chart => chart && chart.setOption(chartMotionOptions()))
}

const DETECTION_CATEGORY_LABELS = {
  Normal: '正常', Bent: '弯曲', Deformed: '形变',
  Rusty: '锈蚀', Missing: '缺失', Compromised: '结构损伤'
}

// ── 计算属性 ──

const inUseRate = computed(() => ratio(deviceStatus.inUse, totalDevices.value))
const employeeActiveRate = computed(() => ratio(employeeStatus.active, totalEmployees.value))
const maintenanceRate = computed(() => ratio(deviceStatus.maintenance, totalDevices.value))

const deviceTypeStats = reactive({
  imageCapture: null,
  imageCaptureInUse: null,
  detection: null,
  detectionInUse: null
})

const topDevices = computed(() => [
  {
    label: '图片采集设备',
    value: deviceTypeStats.imageCapture,
    desc: '负责图像采集与上传',
    meta: `使用中 ${formatNumber(deviceTypeStats.imageCaptureInUse)} 台`
  },
  {
    label: '图像检测设备',
    value: deviceTypeStats.detection,
    desc: '负责执行图像检测任务',
    meta: `使用中 ${formatNumber(deviceTypeStats.detectionInUse)} 台`
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
  chartMotionPreference.addEventListener('change', updateChartMotion)
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
  chartMotionPreference.removeEventListener('change', updateChartMotion)
  window.clearInterval(refreshTimer)
  window.removeEventListener('resize', resizeCharts)
  Object.values(charts).forEach(c => c && c.dispose())
})

// ── 数据获取 ──

async function refreshAll() {
  if (refreshing.value || disposed) return
  refreshing.value = true
  try {
    await Promise.all([fetchDashboardStats(), fetchDeviceData(), fetchEmployeeData(), fetchModelStats(), fetchWorkUnitSummary(), fetchDuplicateSummary(), fetchQualityWorkload()])
    if (!disposed) await updateChartData()
    if (!failedSections.value.length && !trendLoading.value && charts.region) lastUpdated.value = beijingDateTime()
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
  if (!failedSections.value.length && !trendLoading.value) lastUpdated.value = beijingDateTime()
}

async function updateChartData() {
  updateDeviceStatusChart()
  updateEmployeeStatusChart()
  await Promise.all([updateDetectionTrendChart(), updateDetectionDistributionChart(), updateRegionChart()])
}

async function fetchDashboardStats() {
  const owner = historicalAccountScope()
  try {
    const res = await dashboardRequest('总览', '/api/dashboard/stats')
    const s = res.data?.data || {}
    if (disposed) return
    totalDetections.value = knownCount(s.detectionCount)
    if (owner === historicalAccountScope()) historicalSummary.value = canViewHistoricalSummary.value && s.historicalSummary && typeof s.historicalSummary === 'object' && !Array.isArray(s.historicalSummary) ? s.historicalSummary : null
    avgMissRate.value = s.avgMissRate
    if (totalDetections.value === null) markSectionFailed('总览')
  } catch { /* 保留旧值，统一显示失败提示。 */ }
}

async function fetchDeviceData() {
  try {
    const res = await dashboardRequest('设备', '/api/devices/stats')
    const stats = res.data?.data || {}
    if (disposed) return
    deviceStatus.inUse = knownCount(stats.inUse)
    deviceStatus.offline = knownCount(stats.offline)
    deviceStatus.maintenance = knownCount(stats.maintenance)
    deviceStatus.unused = knownCount(stats.idle)
    totalDevices.value = knownCount(stats.total)
    deviceTypeStats.imageCapture = knownCount(stats.imageCapture)
    deviceTypeStats.imageCaptureInUse = knownCount(stats.imageCaptureInUse)
    deviceTypeStats.detection = knownCount(stats.detection)
    deviceTypeStats.detectionInUse = knownCount(stats.detectionInUse)
    if ([totalDevices.value, ...Object.values(deviceStatus), ...Object.values(deviceTypeStats)].some(value => value === null)) markSectionFailed('设备')
  } catch { /* 保留旧值。 */ }
}

async function fetchEmployeeData() {
  try {
    const res = await dashboardRequest('人员', '/api/employees/stats')
    const stats = res.data?.data || {}
    if (disposed) return
    employeeStatus.active = knownCount(stats.active)
    employeeStatus.vacation = knownCount(stats.vacation)
    employeeStatus.resigned = knownCount(stats.resigned)
    employeeStatus.detection = knownCount(stats.detection)
    employeeStatus.collection = knownCount(stats.collection)
    employeeStatus.maintenance = knownCount(stats.maintenance)
    totalEmployees.value = knownCount(stats.total)
    if ([totalEmployees.value, ...Object.values(employeeStatus)].some(value => value === null)) markSectionFailed('人员')
  } catch { /* 保留旧值。 */ }
}

async function fetchModelStats() {
  if (modelStatsLoading.value || disposed) return
  modelStatsLoading.value = true
  try {
    const res = await dashboardRequest('模型', '/api/dashboard/model-stats')
    if (disposed) return
    if (!Array.isArray(res.data?.data) || res.data.data.some(item => !item || typeof item !== 'object')) throw new Error('模型统计格式异常')
    modelStats.value = res.data.data
  } catch { if (!disposed) markSectionFailed('模型') }
  finally { if (!disposed) modelStatsLoading.value = false }
}

// ── 图表更新 ──

const CHART_COLORS = {
  blue: '#2563eb', green: '#059669', amber: '#d97706',
  violet: '#7c3aed', red: '#dc2626', slate: '#94a3b8',
  purple: '#8b5cf6', cyan: '#0891b2', pale: '#cbd5e1'
}

async function updateDetectionTrendChart() {
  if (!charts.detectionTrend) return
  const generation = ++trendRequestGeneration
  const timeRange = detectionTimeRange.value
  trendLoading.value = true
  // Clear the previous range immediately so it cannot appear under a new range label.
  if (renderedTrendRange !== timeRange) {
    charts.detectionTrend.setOption(buildEmptyOption('正在读取所选范围…'), true)
    chartReadouts.trend={rows:[],loaded:false,scope:trendScopeLabel.value}
  }
  try {
    const res = await request.get('/api/statistics/detection-trend', { params: { timeRange } })
    if (disposed || generation !== trendRequestGeneration) return
    if (res.data?.code !== 200 || !Array.isArray(res.data?.data)) throw new Error('趋势统计格式异常')
    failedSections.value = failedSections.value.filter(item => item !== '检测趋势')
    charts.detectionTrend.clear()
    renderedTrendRange = timeRange
    const data = res.data?.data || []
    if (!data.length) { chartReadouts.trend={rows:[],loaded:true,scope:trendScopeLabel.value};charts.detectionTrend.setOption(buildEmptyOption('暂无趋势数据')); return }
    const countKeys = ['total', 'normal', 'bent', 'deformed', 'rusty', 'missing', 'compromised']
    if (data.some(item => !item || countKeys.some(key => knownCount(item[key]) === null))) throw new Error('趋势统计字段不完整')
    chartReadouts.trend={rows:data.map(item=>Object.fromEntries([['period',item.date],...countKeys.map(key=>[key,knownCount(item[key])])])),loaded:true,scope:trendScopeLabel.value}

    const labels = data.map(i => i.date)
    const pick = (k) => data.map(i => knownCount(i[k]))

    charts.detectionTrend.setOption({
      ...chartMotionOptions(),
      color: [CHART_COLORS.blue, CHART_COLORS.green, CHART_COLORS.amber, CHART_COLORS.violet, CHART_COLORS.red, CHART_COLORS.purple, CHART_COLORS.cyan],
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#fff',
        borderColor: '#e2e8f0',
        textStyle: { color: '#0f172a', fontSize: 13 },
        boxShadow: '0 12px 40px rgba(15,23,42,0.12)'
      },
      legend: { top: 0, textStyle: { color: '#475569', fontSize: 12 }, itemGap: 16 },
      grid: { left: 20, right: 18, bottom: 20, top: 48, containLabel: true },
      xAxis: {
        type: 'category', data: labels,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#475569', fontSize: 12 }
      },
      yAxis: [{
        type: 'value', name: '图片数', minInterval: 1,
        splitLine: { lineStyle: { color: '#f1f5f9' } },
        axisLabel: { color: '#475569', fontSize: 12 }
      }, {
        type: 'value', name: '目标数', minInterval: 1,
        splitLine: { show: false }, axisLabel: { color: '#475569', fontSize: 12 }
      }],
      series: [
        {
          name: '任务图片数', type: 'line', smooth: true, symbolSize: 6,
          lineStyle: { width: 3 }, symbol: 'circle',
          areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1, [
            { offset: 0, color: 'rgba(37,99,235,0.18)' },
            { offset: 1, color: 'rgba(37,99,235,0.0)' }
          ])},
          data: pick('total')
        },
        { name: '正常', type: 'bar', yAxisIndex: 1, stack: 'result', barMaxWidth: 14, itemStyle: { borderRadius: [4,4,0,0] }, data: pick('normal') },
        { name: '弯曲', type: 'bar', yAxisIndex: 1, stack: 'result', barMaxWidth: 14, data: pick('bent') },
        { name: '形变', type: 'bar', yAxisIndex: 1, stack: 'result', barMaxWidth: 14, data: pick('deformed') },
        { name: '锈蚀', type: 'bar', yAxisIndex: 1, stack: 'result', barMaxWidth: 14, data: pick('rusty') },
        { name: '缺失', type: 'bar', yAxisIndex: 1, stack: 'result', barMaxWidth: 14, data: pick('missing') },
        { name: '结构损伤', type: 'bar', yAxisIndex: 1, stack: 'result', barMaxWidth: 14, data: pick('compromised') }
      ]
    })
  } catch {
    if (!disposed && generation === trendRequestGeneration) {
      markSectionFailed('检测趋势')
      renderedTrendRange = null
      charts.detectionTrend.setOption(buildEmptyOption('趋势加载失败，请刷新重试'), true)
    }
  } finally {
    if (!disposed && generation === trendRequestGeneration) trendLoading.value = false
  }
}

async function updateDetectionDistributionChart() {
  if (!charts.detectionDistribution) return
  try {
    const res = await dashboardRequest('检测分布', '/api/statistics/detection-distribution')
    if (disposed) return
    charts.detectionDistribution.clear()
    const resultMap = { 正常: null, 弯曲: null, 形变: null, 锈蚀: null, 缺失: null, 结构损伤: null }
    const data = res.data?.data
    if (!Array.isArray(data)) throw new Error('分布统计格式异常')
    if (!data.length) { chartReadouts.distribution={rows:[],loaded:true};charts.detectionDistribution.setOption(buildEmptyOption('暂无分布数据')); return }
    if (data.every(item => item?.count == null)) { chartReadouts.distribution={rows:[],loaded:false};charts.detectionDistribution.setOption(buildEmptyOption('尚无已记录的分类统计')); return }
    data.forEach(item => {
      const label = DETECTION_CATEGORY_LABELS[item.result] || item.result
      if (Object.hasOwn(resultMap, label)) resultMap[label] = knownCount(item.count)
    })
    if (Object.values(resultMap).some(v => v === null)) throw new Error('分布统计字段不完整')
    chartReadouts.distribution={rows:Object.entries(resultMap).map(([label,count])=>({label,count})),loaded:true}
    if (Object.values(resultMap).every(v => v === 0)) { charts.detectionDistribution.setOption(buildEmptyOption('暂无分布数据')); return }

    charts.detectionDistribution.setOption({
      ...chartMotionOptions(),
      color: [CHART_COLORS.green, CHART_COLORS.amber, CHART_COLORS.violet, CHART_COLORS.red, CHART_COLORS.purple, CHART_COLORS.cyan],
      tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#e2e8f0', textStyle: { color: '#0f172a' } },
      legend: { bottom: 0, textStyle: { color: '#475569', fontSize: 12 } },
      series: [{
        type: 'pie', radius: ['50%', '74%'], center: ['50%', '44%'],
        label: { formatter: '{b}\n{d}%', fontSize: 12, color: '#475569' },
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
  } catch { if (!disposed) { markSectionFailed('检测分布'); charts.detectionDistribution.setOption(buildEmptyOption('分布加载失败，请刷新重试'), true) } }
}

function updateDeviceStatusChart() {
  if (!charts.deviceStatus) return
  charts.deviceStatus.clear()
  const counts = Object.values(deviceStatus)
  if (counts.some(value => value === null)) {
    charts.deviceStatus.setOption(buildEmptyOption('设备状态统计尚未完整读取'), true)
    return
  }
  if (counts.every(value => value === 0)) {
    charts.deviceStatus.setOption(buildEmptyOption('暂无已登记的设备状态'), true)
    return
  }
  charts.deviceStatus.setOption({
    ...chartMotionOptions(),
    color: [CHART_COLORS.blue, CHART_COLORS.slate, CHART_COLORS.amber, CHART_COLORS.pale],
    tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#e2e8f0', textStyle: { color: '#0f172a' } },
    legend: { bottom: 0, textStyle: { color: '#475569', fontSize: 12 } },
    series: [{
      type: 'pie', radius: ['44%', '70%'], center: ['50%', '44%'],
      label: { formatter: '{b}\n{c} 台', fontSize: 12, color: '#475569' },
      itemStyle: { borderRadius: 12, borderColor: '#fff', borderWidth: 3 },
      emphasis: { scaleSize: 8 },
      data: [
        { name: '使用中', value: deviceStatus.inUse },
        { name: '离线', value: deviceStatus.offline },
        { name: '维护中', value: deviceStatus.maintenance },
        { name: '未使用', value: deviceStatus.unused }
      ]
    }]
  })
}

function updateEmployeeStatusChart() {
  if (!charts.employeeStatus) return
  charts.employeeStatus.clear()
  const counts = [employeeStatus.active, employeeStatus.vacation, employeeStatus.resigned]
  if (counts.some(value => value === null)) {
    charts.employeeStatus.setOption(buildEmptyOption('人员状态统计尚未完整读取'), true)
    return
  }
  if (counts.every(value => value === 0)) {
    charts.employeeStatus.setOption(buildEmptyOption('暂无已登记的人员状态'), true)
    return
  }
  charts.employeeStatus.setOption({
    ...chartMotionOptions(),
    color: [CHART_COLORS.green, CHART_COLORS.amber, CHART_COLORS.slate],
    tooltip: { trigger: 'item', backgroundColor: '#fff', borderColor: '#e2e8f0', textStyle: { color: '#0f172a' } },
    legend: { bottom: 0, textStyle: { color: '#475569', fontSize: 12 } },
    series: [{
      type: 'pie', radius: ['44%', '70%'], center: ['50%', '44%'],
      label: { formatter: '{b}\n{d}%', fontSize: 12, color: '#475569' },
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
    const data = res.data?.data
    if (!Array.isArray(data)) throw new Error('地区统计格式异常')
    if (!data.length) { chartReadouts.region={rows:[],loaded:true};charts.region.setOption(buildEmptyOption('暂无地区数据')); return }

    const regions = data.map(i => i.region)
    const imageCounts = data.map(i => knownCount(i.imageCount))
    const taskCounts = data.map(i => knownCount(i.taskCount))
    if ([...imageCounts, ...taskCounts].some(value => value === null)) throw new Error('地区统计字段不完整')
    chartReadouts.region={rows:data.map((item,index)=>({label:item.region,images:imageCounts[index],tasks:taskCounts[index]})),loaded:true}

    charts.region.setOption({
      ...chartMotionOptions(),
      color: [CHART_COLORS.cyan, CHART_COLORS.blue],
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#fff',
        borderColor: '#e2e8f0',
        textStyle: { color: '#0f172a', fontSize: 13 },
        axisPointer: { type: 'shadow' }
      },
      legend: { top: 0, textStyle: { color: '#475569', fontSize: 12 }, itemGap: 16 },
      grid: { left: 20, right: 18, bottom: 20, top: 40, containLabel: true },
      xAxis: {
        type: 'category', data: regions,
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisLabel: { color: '#475569', fontSize: 12, rotate: regions.length > 6 ? 30 : 0 }
      },
      yAxis: [
        {
          type: 'value', name: '图片数',
          splitLine: { lineStyle: { color: '#f1f5f9' } },
          axisLabel: { color: '#475569', fontSize: 12 }
        },
        {
          type: 'value', name: '任务数',
          splitLine: { show: false },
          axisLabel: { color: '#475569', fontSize: 12 }
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
  } catch { if (!disposed) { markSectionFailed('地区采集'); charts.region.setOption(buildEmptyOption('地区数据加载失败，请刷新重试'), true) } }
}

function buildEmptyOption(text) {
  return {
    ...chartMotionOptions(),
    title: {
      text, left: 'center', top: 'center',
      textStyle: { color: '#475569', fontSize: 14, fontWeight: 500 }
    }
  }
}

// ── 工具函数 ──

function resizeCharts() { Object.values(charts).forEach(c => c && c.resize()) }

function formatNumber(value) { return knownCount(value)?.toLocaleString('zh-CN') ?? '—' }

function ratio(numerator, denominator) {
  const count = knownCount(numerator)
  const total = knownCount(denominator)
  if (count === null || total === null || total === 0 || count > total) return null
  return (count / total * 100).toFixed(1)
}

function rawStatistic(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return '未知'
  if (typeof value === 'string' && !value.trim()) return '未知'
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? `${number}（原始值，单位未统一）` : '未知'
}

function getModelUsagePercent(taskCount) {
  if (!modelStats.value.length) return null
  const counts = modelStats.value.map(model => knownCount(model.taskCount))
  if (counts.some(value => value === null)) return null
  return ratio(taskCount, Math.max(...counts))
}
</script>

<style scoped>
.home-page > .dashboard-refresh-note { margin:0; }
.home-page .hero-panel > .app-panel-title { font-size:16px; font-weight:600; margin-bottom:16px; }
.home-page .hero-panel .hero-telemetry { margin:0 0 20px; gap:12px; }
.home-page .hero-panel .metric-chip { padding:0; min-height:24px; border:0; border-radius:0; background:transparent; color:var(--app-text-muted); font-weight:400; }
.home-page .hero-highlights { gap:0; margin-top:0; }
.home-page .hero-highlights > a:first-child { border-left:0; }
.home-page .hl-header { margin-bottom:12px; }
.home-page .hl-icon { width:28px; height:28px; border-radius:7px; background:var(--app-surface-muted); color:var(--app-text-secondary); }
.home-page .hl-label { line-height:1.8; font-size:12px; }
.home-page .hl-trend { color:var(--app-text-muted); background:transparent; font-weight:400; }

/* ═══════════════════════════════════════════════════════
   Home Dashboard — 仪表板样式
   ═══════════════════════════════════════════════════════ */

.home-page {
  display: flex;
  flex-direction: column;
  gap:24px;
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
  background: var(--app-surface);
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
  background: var(--app-surface);
  border: 1px solid rgba(37, 99, 235, 0.10);
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast), box-shadow var(--app-transition-fast), transform var(--app-transition-fast);
  box-shadow: var(--app-shadow-xs);
}

.highlight-card::after {
  content: none;
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


.hl-trend {
  font-size: 11px; font-weight: 600;
  padding: 2px 8px; border-radius: 999px;
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
}


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
  background: var(--app-surface);
  border: 1px solid rgba(15, 23, 42, 0.05);
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast), box-shadow var(--app-transition-fast), transform var(--app-transition-fast);
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
  transition: opacity var(--app-transition-fast), transform var(--app-transition-fast);
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
  transition: width var(--app-transition-base);
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
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast), box-shadow var(--app-transition-fast);
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
  background: var(--app-primary);
  transition: width var(--app-transition-base);
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
  background: var(--app-surface);
  border: 1px solid rgba(37, 99, 235, 0.08);
  cursor: pointer;
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast), box-shadow var(--app-transition-fast), transform var(--app-transition-fast);
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
.qs-icon-slate { color: var(--app-text-secondary); background: var(--app-info-soft); }

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
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast), transform var(--app-transition-fast);
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
  transition: opacity var(--app-transition-fast), transform var(--app-transition-fast);
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
  transition: width var(--app-transition-base);
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
.dashboard-data-note { margin: 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.75; overflow-wrap: anywhere; }
.dashboard-source-note { margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--app-border); color: var(--app-text-secondary); font-size: 12px; line-height: 1.8; }
.dashboard-source-note summary { width: fit-content; max-width: 100%; cursor: pointer; color: var(--app-warning); font-weight: 550; }
.dashboard-source-note summary .app-icon { margin-right: 5px; vertical-align: middle; }
.dashboard-source-note p { max-width: 80ch; }
.dashboard-source-note dl { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(0, 2fr); gap: 8px 16px; max-width: 600px; }
.dashboard-source-note :is(dt, dd) { margin: 0; overflow-wrap: anywhere; }
.workflow-summaries { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 20px 0; }
.workflow-summary { padding: 20px; min-width: 0; }
.workflow-summary h3 { font-size: 14px; margin: 0 0 6px; }
.workflow-summary p { font-size: 12px; line-height: 1.7; color: var(--app-text-muted); }
@media (max-width: 900px) { .workflow-summaries { grid-template-columns: 1fr; } }
</style>
