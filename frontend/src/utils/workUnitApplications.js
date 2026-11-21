export function needsDetectionBatch(row) {
  return /^WU-[a-f0-9]{32}$/.test(row.workUnitId || '') && row.strategy !== 'OSS_FOLDER'
    && !row.sourceBatchId && !row.batchId && !!row.applicantUserId
    && ((row.status === 'WAITING' && !row.assigneeUserId)
      || (row.status === 'ASSIGNED' && row.assigneeUserId === row.applicantUserId))
}
