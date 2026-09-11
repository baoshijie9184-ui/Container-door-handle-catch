import request from './request'

export function getWorkUnitSummary() {
  return request.get('/api/dashboard/work-unit-summary')
}

export function getDuplicateSummary() {
  return request.get('/api/dashboard/duplicate-summary')
}

/**
 * 获取仪表盘统计数据
 * @returns {Promise} 返回统计数据
 */
export function getDashboardStats() {
  return request.get('/api/dashboard/stats')
}

/**
 * 获取检测记录趋势数据
 * @param {string} timeRange - 时间范围：week/month/year
 * @returns {Promise} 返回趋势数据
 */
export function getDetectionTrend(timeRange = 'month') {
  return request.get(`/api/statistics/detection-trend`, {
    params: { timeRange }
  });
}

/**
 * 获取检测结果分布数据
 * @returns {Promise} 返回分布数据
 */
export function getDetectionDistribution() {
  // 使用统计API
  return request.get('/api/statistics/detection-distribution')
}

/**
 * 获取检测记录列表
 * @param {Object} params - 查询参数 {page, size}
 * @returns {Promise} 返回检测记录列表
 */
export function getDetectionRecords(params) {
  return request.get('/api/detection-records', { params })
}

/**
 * 获取检测记录详情
 * @param {number} id - 记录ID
 * @returns {Promise} 返回检测记录详情
 */
export function getDetectionDetail(id) {
  return request.get(`/api/detection-records/detail?id=${id}`)
}

/**
 * 获取人员列表
 * @param {Object} params - 查询参数
 * @returns {Promise} 返回人员列表
 */
export function getEmployees(params) {
  return request.get('/api/employees', { params })
}

/**
 * 获取设备列表
 * @param {Object} params - 查询参数
 * @returns {Promise} 返回设备列表
 */
export function getDevices(params) {
  return request.get('/api/devices', { params })
} 
