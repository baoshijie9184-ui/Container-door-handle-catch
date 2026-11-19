const test = require('node:test')
const assert = require('node:assert/strict')
const { importFrontendModule } = require('./helpers/project-source.cjs')

test('personnel numbers preserve the serial when selecting or changing positions', async () => {
  const { employeeNumberFor, employeeNumberSuffix, employeeTypeOptions } =
    await importFrontendModule('src', 'utils', 'employeeNumbers.js')
  for (const [role, prefix] of Object.entries({
    SUPERVISOR: 'SUP', DETECTION: 'DET', COLLECTION: 'COL', MAINTENANCE: 'MNT'
  })) {
    assert(employeeTypeOptions.some(option => option.value === role))
    for (const prior of ['0001', 'EMP-0001', 'DET-0001', 'col-0001']) {
      assert.equal(employeeNumberFor(role, prior), prefix + '-0001')
    }
    assert.equal(employeeNumberFor(role, ''), '')
  }
  assert.equal(employeeNumberFor('DETECTION', 'LAB-INSPECTOR-01'), 'DET-LAB-INSPECTOR-01')
  assert.equal(employeeNumberSuffix('DET-LAB-INSPECTOR-01'), 'LAB-INSPECTOR-01')
})
