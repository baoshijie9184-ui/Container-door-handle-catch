import { computed, reactive, ref, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchDefectGallery } from '../api/detection'
import { knownCount } from '../utils/countPresentation'

const resolvePageNumber = (page, fallback) => {
  const value = Number(page)
  return Number.isInteger(value) && value > 0 ? value : fallback
}

function readGalleryPage(data) {
  if (!Array.isArray(data?.records) || knownCount(data.total) === null) throw new Error('缺陷任务列表或数量未完整读取，请重新核对')
  const taskIds = new Set()
  for (const task of data.records) {
    if (!task || typeof task.taskId !== 'string' || !task.taskId.trim() || taskIds.has(task.taskId)) throw new Error('缺陷任务编号未完整读取，请重新核对')
    taskIds.add(task.taskId)
    for (const key of ['previewImages','originalImages','defectEvidence']) {
      const items = task[key]
      if (items == null) continue
      if (!Array.isArray(items) || items.some(item => !item || typeof item !== 'object' || Array.isArray(item))) throw new Error('缺陷任务预览资料未完整读取，请重新核对')
    }
  }
  return data
}

export function useDefectGallery() {
  const defectGalleryLoading = ref(false)
  const defectGalleryError = ref('')
  let loadGeneration = 0, disposed = false
  let pendingKey = ''
  onBeforeUnmount(() => { disposed = true; loadGeneration++ })
  const defectGalleryRecords = ref([])
  const defectGalleryTotal = ref(null)
  const appliedParams = ref(null)
  const defectGalleryPage = ref(1)
  const defectGalleryPageSize = ref(8)
  const defectFilters = reactive({
    defectType: '',
    severityLevel: '',
    deviceName: '',
    batchNo: '',
    modelId: null
  })
  const hasDefectFilters = computed(() => !!(defectFilters.defectType.trim() || defectFilters.severityLevel || defectFilters.deviceName.trim() || defectFilters.batchNo.trim() || defectFilters.modelId))

  const buildDefectGalleryParams = (page = defectGalleryPage.value) => {
    const targetPage = resolvePageNumber(page, defectGalleryPage.value)
    const params = {
      page: targetPage,
      size: defectGalleryPageSize.value
    }
    if (defectFilters.defectType.trim()) params.defectType = defectFilters.defectType.trim()
    if (defectFilters.severityLevel) params.severityLevel = defectFilters.severityLevel
    if (defectFilters.deviceName.trim()) params.deviceName = defectFilters.deviceName.trim()
    if (defectFilters.batchNo.trim()) params.batchNo = defectFilters.batchNo.trim()
    if (defectFilters.modelId) params.modelId = defectFilters.modelId
    return params
  }

  const loadDefectGallery = async (page = defectGalleryPage.value) => {
    if (disposed) return
    const targetPage = resolvePageNumber(page, defectGalleryPage.value)
    const params = buildDefectGalleryParams(targetPage)
    const key = JSON.stringify(params)
    if (defectGalleryLoading.value && pendingKey === key) return
    const generation = ++loadGeneration
    pendingKey = key
    if (JSON.stringify(params) !== JSON.stringify(appliedParams.value)) { defectGalleryRecords.value = []; defectGalleryTotal.value = null }
    defectGalleryLoading.value = true
    defectGalleryError.value = ''
    try {
      const response = await fetchDefectGallery(params)
      if (disposed || generation !== loadGeneration) return
      if (response.data?.code === 200) {
        const data = readGalleryPage(response.data.data)
        defectGalleryRecords.value = data.records
        defectGalleryTotal.value = knownCount(data.total)
        appliedParams.value = params
        defectGalleryPage.value = targetPage
      } else {
        defectGalleryError.value = response.data?.message || '获取缺陷证据库失败'
        ElMessage.error(defectGalleryError.value)
      }
    } catch (error) {
      if (disposed || generation !== loadGeneration) return
      if ([401,403].includes(error.response?.status)) { defectGalleryRecords.value = []; defectGalleryTotal.value = null; appliedParams.value = null }
      defectGalleryError.value = error.response?.data?.message || error.message || '获取缺陷证据库失败'
      ElMessage.error(defectGalleryError.value)
    } finally {
      if (!disposed && generation === loadGeneration) defectGalleryLoading.value = false
    }
  }

  const searchDefectGallery = () => {
    defectGalleryPage.value = 1
    loadDefectGallery(1)
  }

  const resetDefectGalleryFilters = () => {
    defectFilters.defectType = ''
    defectFilters.severityLevel = ''
    defectFilters.deviceName = ''
    defectFilters.batchNo = ''
    defectFilters.modelId = null
    searchDefectGallery()
  }

  const onDefectGallerySizeChange = (size) => {
    defectGalleryPageSize.value = size
    defectGalleryPage.value = 1
    loadDefectGallery(1)
  }

  const defectFiltersDirty = computed(() => !!appliedParams.value && ['defectType','severityLevel','deviceName','batchNo','modelId'].some(key => (buildDefectGalleryParams()[key] ?? '') !== (appliedParams.value[key] ?? '')))

  return {
    defectGalleryLoading,
    defectGalleryError,
    hasDefectFilters,
    defectFiltersDirty,
    defectGalleryRecords,
    defectGalleryTotal,
    defectGalleryPage,
    defectGalleryPageSize,
    defectFilters,
    buildDefectGalleryParams,
    loadDefectGallery,
    searchDefectGallery,
    resetDefectGalleryFilters,
    onDefectGallerySizeChange
  }
}
