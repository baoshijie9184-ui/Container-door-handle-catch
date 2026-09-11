import { onBeforeUnmount } from 'vue'

export const useSingleImageUploadPreview = ({
  form,
  fileList,
  detectionResult,
  annotatedImageUrl,
  onReset = () => {}
}) => {
  let previewObjectUrl = ''

  const releasePreview = () => {
    if (previewObjectUrl) {
      URL.revokeObjectURL(previewObjectUrl)
      previewObjectUrl = ''
    }
  }

  const handleUploadChange = (uploadFile) => {
    const file = uploadFile.raw
    if (!file) return

    releasePreview()
    const previewUrl = uploadFile.url || URL.createObjectURL(file)
    previewObjectUrl = previewUrl
    uploadFile.url = previewUrl
    form.imageFile = file
    fileList.value = [uploadFile]
    detectionResult.value = null
    annotatedImageUrl.value = ''
    onReset()
  }

  const handleRemove = () => {
    releasePreview()
    form.imageFile = null
    fileList.value = []
    detectionResult.value = null
    annotatedImageUrl.value = ''
    onReset()
  }

  onBeforeUnmount(releasePreview)

  return { handleUploadChange, handleRemove }
}
