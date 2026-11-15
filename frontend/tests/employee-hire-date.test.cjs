const test = require('node:test'), assert = require('node:assert/strict')
const { readFrontendFile } = require('./helpers/project-source.cjs')
const subject = import('data:text/javascript;base64,' + Buffer.from(readFrontendFile('src', 'utils', 'employeeHireDate.js')).toString('base64'))

test('calendar selection accepts exact calendar dates without timezone conversion', async () => {
  const { isCalendarHireDate } = await subject
  for (const value of ['2020-02-29', '2000-02-29', '2026-11-15', '0001-01-01', '9999-12-31']) assert.equal(isCalendarHireDate(value), true, value)
  for (const value of ['1900-02-29', '2021-02-29', '2026-04-31', '2026-13-01', '2026-00-10', '2026-01-00', '0000-01-01', '2026-1-01', '2026-01-01T00:00:00', ' 2026-01-01 ', '', null]) assert.equal(isCalendarHireDate(value), false, String(value))
})

test('legacy text survives initial empty widget projection and unrelated edits', async () => {
  const { legacyHireDate, setHireDateSelection } = await subject
  for (const value of ['2020年春', '待核对', ' 2020-01-01 ', '<img src=x>']) {
    const form = { name: 'Before', hireDate: value }
    assert.equal(legacyHireDate(form.hireDate), value)
    setHireDateSelection(form, null); setHireDateSelection(form, '')
    form.name = 'After'
    assert.deepEqual(form, { name: 'After', hireDate: value })
    setHireDateSelection(form, '2020-03-01')
    assert.equal(form.hireDate, '2020-03-01')
    assert.equal(legacyHireDate(form.hireDate), '')
  }
})

test('empty dates stay empty and normal dates retain the existing clear control', async () => {
  const { legacyHireDate, setHireDateSelection } = await subject
  const form = { hireDate: null }
  assert.equal(legacyHireDate(form.hireDate), '')
  setHireDateSelection(form, null); assert.equal(form.hireDate, null)
  setHireDateSelection(form, '2026-11-15'); assert.equal(form.hireDate, '2026-11-15')
  setHireDateSelection(form, '2026-02-30'); assert.equal(form.hireDate, '2026-11-15')
  setHireDateSelection(form, ''); assert.equal(form.hireDate, null)
})

test('employee form separates raw legacy display from the calendar model', () => {
  const source = readFrontendFile('src', 'views', 'employee', 'EmployeeForm.vue')
  assert.match(source, /v-model="hireDateModel"/)
  assert.doesNotMatch(source, /v-model="employeeForm\.hireDate"/)
  assert.match(source, /\{\{ legacyHireDateText \}\}/)
  assert.match(source, /set:value=>setHireDateSelection\(employeeForm,value\)/)
  assert.doesNotMatch(source, /v-html/)
})
