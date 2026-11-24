const test = require('node:test');
const assert = require('node:assert/strict');
const trend = import('../src/utils/dashboardTrend.js');

test('the dashboard plots twelve Beijing calendar months with unknown gaps and genuine zeros', async () => {
  const { detectionTrendRows } = await trend;
  const rows = detectionTrendRows([
    { date: '2025-12', total: 21, taskCount: 2, classifiedTasks: 1, normal: 0 },
    { date: '2026-10', total: 0, taskCount: 1, classifiedTasks: 0 }
  ], 'month', new Date('2026-11-24T04:00:00Z'));
  assert.equal(rows.length, 12);
  assert.equal(rows[0].period, '2025-12');
  assert.equal(rows[0].normal, 0);
  assert.equal(rows[0].bent, null);
  assert.match(rows[0].classificationCoverage, /^1 \/ 2/);
  assert.deepEqual(rows.slice(7, 10).map(row => row.period), ['2026-07', '2026-08', '2026-09']);
  assert(rows.slice(7, 10).every(row => row.total === null && row.coverage === '无已完成任务记录'));
  assert.equal(rows[10].total, 0);
  assert.equal(rows[10].normal, null);
  assert.equal(rows[11].period, '2026-11');
});

test('the dashboard uses the business date at month and day boundaries, including empty ranges', async () => {
  const { detectionTrendRows } = await trend;
  const now = new Date('2026-11-30T16:01:00Z');
  const rows = detectionTrendRows([], 'week', now);
  assert.equal(rows.length, 7);
  assert.equal(rows[0].period, '2026-11-25');
  assert.equal(rows[6].period, '2026-12-01');
  assert.equal(detectionTrendRows([], 'month', now).at(-1).period, '2026-12');
  assert.deepEqual(detectionTrendRows([], 'year', now), []);
  assert.deepEqual(detectionTrendRows([{ date: '2023', total: 3 }], 'year', now).map(row => row.period), ['2023', '2024', '2025', '2026']);
});
