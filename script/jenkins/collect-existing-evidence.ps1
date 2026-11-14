$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if ($root.Replace('\', '/') -cne 'D:/AI/lunwen1/DoorHandleCatch/work/jenkins/ci-workspaces/monolith') {
    throw 'Evidence recollection must use the existing dedicated Jenkins checkout.'
}
Set-Location -LiteralPath $root
if ($env:ACTION -cne 'collect-existing-evidence' -or $env:DOORHANDLE_CI_SCOPE -cne 'source' -or $env:CI_ECS_VERIFIED -cne 'false') {
    throw 'Evidence recollection cannot run project verification or authorize release.'
}
foreach ($name in @('LEGACY_SOURCE_SNAPSHOT','LEGACY_SOURCE_ECS_SNAPSHOT','LOCAL_ARTIFACTS_SNAPSHOT','LOCAL_ARTIFACTS_ECS_SNAPSHOT',
    'COLD_STORES_SNAPSHOT','COLD_STORES_ECS_SNAPSHOT','COLD_HISTORY_SNAPSHOT','COLD_HISTORY_ECS_SNAPSHOT',
    'LOCAL_MYSQL_SNAPSHOT','LOCAL_MYSQL_ECS_SNAPSHOT','LOCAL_MYSQL_FIXTURE_SETTINGS','PROJECT_MYSQL_SNAPSHOT',
    'PROJECT_MYSQL_MANIFEST_SHA256','PROJECT_MYSQL_ARCHIVE_SHA256','REMAINING_SYSTEM_DATA_SNAPSHOT','REMAINING_SYSTEM_DATA_ECS_SNAPSHOT',
    'DOORHANDLE_CI_FIXTURE_MANIFEST','DOORHANDLE_CI_FIXTURE_SETTINGS','CANDIDATE_BUILD_TOOLS_ARCHIVE','COMPACT_CUTOVER_SETTINGS',
    'COMPATIBLE_BACKEND_IMAGE','COMPATIBLE_RUNNER_IMAGE','REHEARSAL_MEMORY_EXTRACTION_MODEL','FAILED_NATIVE_BUILD_NUMBER','FAILED_MYSQL_DATA_BUILDS')) {
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) { throw 'Recollection accepts only a retained build number, not business or runtime inputs.' }
}
foreach ($name in @('DOORHANDLE_CI_AUTO_COMPACT_FIXTURES','PRODUCTION_RELEASE_ENABLED','DOORHANDLE_COMPACT_RELEASE_READY','DOORHANDLE_COMPACT_REHEARSAL_READY','REHEARSAL_KEEP')) {
    if ([Environment]::GetEnvironmentVariable($name) -ceq 'true') { throw 'Recollection cannot enable fixtures, application release or rehearsal.' }
}
if ($env:EXISTING_EVIDENCE_BUILD -cnotmatch '\A[1-9][0-9]{0,8}\z' -or $env:BUILD_NUMBER -cnotmatch '\A[1-9][0-9]{0,8}\z' -or
    [long]$env:EXISTING_EVIDENCE_BUILD -ge [long]$env:BUILD_NUMBER -or $env:GIT_COMMIT -cnotmatch '\A[a-f0-9]{40}\z' -or
    $env:RELEASE_TAG -cne ('ci-' + $env:BUILD_NUMBER + '-' + $env:GIT_COMMIT.Substring(0,12)) -or
    $env:DOORHANDLE_ECS_INSTANCE_ID -cne 'i-2zeieuov2aum486jm1ek' -or $env:DOORHANDLE_ECS_MACHINE_ID -cnotmatch '\A[a-f0-9]{32}\z') {
    throw 'Recollection requires exact earlier build, current collector commit and admitted ECS identities.'
}
$python = $env:LOCAL_PYTHON_EXE
if ([string]::IsNullOrWhiteSpace($python)) { $python = $env:PYTHON_EXE }
if ([string]::IsNullOrWhiteSpace($python) -or -not [IO.Path]::IsPathRooted($python) -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Use the existing absolute Python executable for CI evidence work.'
}
& $python -B script/jenkins/verify-remote.py recollect --existing-build $env:EXISTING_EVIDENCE_BUILD `
    --collector-commit $env:GIT_COMMIT --collector-release $env:RELEASE_TAG `
    --instance-id $env:DOORHANDLE_ECS_INSTANCE_ID --machine-id $env:DOORHANDLE_ECS_MACHINE_ID
if ($LASTEXITCODE -ne 0) { throw 'Original ECS evidence recollection failed; original build and retained inputs remain unchanged.' }
