export const employeeTypeOptions = [
  { value: 'SUPERVISOR', label: '主管', prefix: 'SUP' },
  { value: 'DETECTION', label: '门把手检测人员', prefix: 'DET' },
  { value: 'COLLECTION', label: '门把手图片采集人员', prefix: 'COL' },
  { value: 'MAINTENANCE', label: '设备维护人员', prefix: 'MNT' }
]

export function employeeTypeLabel(type) {
  return employeeTypeOptions.find(item => item.value === type)?.label || type || '岗位未记录'
}

export function employeeNumberPrefix(type) {
  return employeeTypeOptions.find(item => item.value === type)?.prefix || ''
}

export function employeeNumberSuffix(number) {
  return (number || '').trim().replace(/^(EMP|SUP|DET|COL|MNT)-/i, '')
}

export function employeeNumberFor(type, number) {
  const prefix = employeeNumberPrefix(type)
  if (!prefix) return (number || '').trim()
  const suffix = employeeNumberSuffix(number)
  return suffix ? prefix + '-' + suffix : ''
}
