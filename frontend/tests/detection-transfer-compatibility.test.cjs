const test = require('node:test'), assert = require('node:assert/strict')
const { readFrontendFile } = require('./helpers/project-source.cjs')
const utility = import(`data:text/javascript;base64,${Buffer.from(readFrontendFile('src', 'utils', 'detectionCreationReview.js')).toString('base64')}`)

test('business failures in an HTTP success are never treated as an empty successful review', async () => {
  const { transferPayload, transferReadIssue } = await utility
  const rows = [{ commandId: 'kept-original-command' }]
  assert.equal(transferPayload(rows), rows)
  assert.equal(transferPayload({ code: 200, data: rows }), rows)
  let rejected
  try { transferPayload({ code: 404, message: 'PRIVATE_DETAILS' }) } catch (error) { rejected = error }
  assert.equal(rejected.status, 404)
  const issue = transferReadIssue(rejected, true)
  assert.equal(issue.clear, true)
  assert.equal(issue.availability, 'MISSING')
  assert.doesNotMatch(issue.message, /PRIVATE_DETAILS|上次快照/)
})

test('optional capability distinguishes unsupported and older unknown servers', async () => {
  const { transferCapability } = await utility
  assert.equal(transferCapability({ enabled: true }), 'UNKNOWN')
  assert.equal(transferCapability({ enabled: true, detectionCreationReviews: false }), 'DISABLED')
  assert.equal(transferCapability({ enabled: true, detectionCreationReviews: true }), 'SUPPORTED')
  assert.equal(transferCapability({ code: 200, data: { enabled: false } }), 'DISABLED')
  assert.throws(() => transferCapability({ detectionCreationReviews: 'true' }))
})

test('authorization errors clear private snapshots, storage errors preserve read-only evidence', async () => {
  const { transferReadIssue, transferFailureStatus } = await utility
  for (const status of [401, 403, 404]) assert.equal(transferReadIssue({ status }, true).clear, true)
  assert.equal(transferFailureStatus({ response: { status: 200, data: { code: 403 } } }), 403)
  assert.equal(transferFailureStatus({ response: { status: 401, data: { code: 200 } } }), 401)
  const issue = transferReadIssue({ status: 503 }, true)
  assert.equal(issue.clear, false)
  assert.equal(issue.availability, '')
  assert.match(issue.message, /上次快照/)
})
