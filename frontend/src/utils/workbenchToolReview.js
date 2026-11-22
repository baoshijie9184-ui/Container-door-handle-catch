export const TOOL_REVIEW_ALLOW = '允许本次调用'
export const TOOL_REVIEW_DENY = '拒绝本次调用'

export function isWorkbenchToolReview(item) {
  const data = item?.data
  return item?.kind === 'QUESTION' && data?.questionType === 'SINGLE' &&
    typeof data.text === 'string' && data.text.startsWith('工具调用待确认') &&
    Array.isArray(data.options) && data.options.length === 2 &&
    data.options.includes(TOOL_REVIEW_ALLOW) && data.options.includes(TOOL_REVIEW_DENY)
}

export function pendingWorkbenchToolReview(items) {
  return items.find(item => item.status === 'PENDING' && isWorkbenchToolReview(item))?.id || ''
}
