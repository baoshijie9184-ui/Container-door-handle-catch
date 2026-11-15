// Preserve historical text without asking a date widget to parse or normalize it.
export function isCalendarHireDate(value) {
  if (typeof value !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  if (year < 1 || month < 1 || month > 12) return false
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return day >= 1 && day <= days[month - 1]
}

export function legacyHireDate(value) {
  return typeof value === 'string' && value !== '' && !isCalendarHireDate(value) ? value : ''
}

export function setHireDateSelection(form, value) {
  if (isCalendarHireDate(value)) form.hireDate = value
  // A widget's empty/invalid projection must not erase an unparseable source value.
  else if ((value == null || value === '') && !legacyHireDate(form.hireDate)) form.hireDate = null
}
