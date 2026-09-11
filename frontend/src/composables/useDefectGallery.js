import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchDefectGallery } from '../api/detection'

const resolvePageNumber = (page, fallback) => {
  const value = Number(page)
  return Number.isInteger(value) && value > 0 ? value : fallback
}

export function useDefectGallery() {
  const defectGalleryLoading = ref(false)
  const defectGalleryRecords = ref([])
  const defectGalleryTotal = ref(0)
  const defectGalleryPage = ref(1)
  const defectGalleryPageSize = ref(8)
  const defectFilters = reactive({
    defectType: '',
    severityLevel: '',
    deviceName: '',
    batchNo: '',
    modelId: null
  })

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
    const targetPage = resolvePageNumber(page, defectGalleryPage.value)
    defectGalleryLoading.value = true
    try {
      const response = await fetchDefectGallery(buildDefectGalleryParams(targetPage))
      if (response.data?.code === 200) {
        const data = response.data.data || {}
        defectGalleryRecords.value = data.records || []
        defectGalleryTotal.value = Number(data.total || 0)
        defectGalleryPage.value = targetPage
      } else {
        ElMessage.error(response.data?.message || '获取缺陷证据库失败')
      }
    } catch (error) {
      console.error('获取缺陷证据库失败:', error)
      ElMessage.error(error.response?.data?.message || '获取缺陷证据库失败')
    } finally {
      defectGalleryLoading.value = false
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

  return {
    defectGalleryLoading,
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
