param([string]$MavenCmd = $env:MAVEN_CMD)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$expectedRoot = 'D:/AI/lunwen1/DoorHandleCatch/work/jenkins/ci-workspaces/monolith'
if ($projectRoot.Replace('\', '/') -ne $expectedRoot) { throw 'Local CI build must use its dedicated D-drive workspace.' }
Set-Location -LiteralPath $projectRoot
if ($env:GIT_COMMIT -notmatch '^[a-f0-9]{40}$' -or $env:RELEASE_TAG -notmatch '^ci-[0-9]+-[a-f0-9]{12}$') {
    throw 'An exact SCM commit and release identifier are required.'
}
$actualCommit = (& git.exe rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $env:GIT_COMMIT) { throw 'Build checkout differs from the pinned SCM commit.' }
if ([string]::IsNullOrWhiteSpace($MavenCmd)) { $MavenCmd = (Get-Command mvn.cmd -CommandType Application -ErrorAction Stop).Source }
if (-not [System.IO.Path]::IsPathRooted($MavenCmd) -or -not (Test-Path -LiteralPath $MavenCmd -PathType Leaf)) {
    throw 'Configure an existing absolute Maven executable for the local build node.'
}
$MavenCmd = (Resolve-Path -LiteralPath $MavenCmd).Path
$artifactDirectory = Join-Path $projectRoot 'artifacts'
New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
if ((Get-Item -LiteralPath $artifactDirectory -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
    throw 'CI artifacts must not be a symbolic link or junction.'
}
$buildDirectory = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'work/local-ci-build'))
if (-not $buildDirectory.StartsWith(($projectRoot + [System.IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The Maven clean/build directory must stay inside this CI workspace.'
}
foreach ($directory in @((Join-Path $projectRoot 'work'), $buildDirectory)) {
    if ((Test-Path -LiteralPath $directory) -and ((Get-Item -LiteralPath $directory -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw 'The Maven clean/build directory must not traverse a symbolic link or junction.'
    }
}
$logFile = Join-Path $artifactDirectory 'local-build.log'
if (Test-Path -LiteralPath $logFile) { throw 'Local build log already exists; use a fresh Jenkins artifacts directory.' }
$receipt = [ordered]@{
    schemaVersion = 1
    startedAt = [DateTimeOffset]::UtcNow.ToString('o')
    commit = $env:GIT_COMMIT
    release = $env:RELEASE_TAG
    scope = 'local compilation and packaging only'
    testsExecuted = $false
    skipTests = $true
    status = 'FAILED'
}
try {
    $arguments = @('-B', '-ntp', '-DskipTests=true', '-DskipITs=true',
        '-Ddoorhandle.isolated-verification=true', ('-Ddoorhandle.verification-root=' + $buildDirectory),
        'clean', 'package')
    & $MavenCmd @arguments 2>&1 | Tee-Object -FilePath $logFile
    $receipt['exitCode'] = $LASTEXITCODE
    if ($LASTEXITCODE -ne 0) { throw 'Local Maven compilation/package failed; inspect local-build.log.' }
    $jars = @(Get-ChildItem -LiteralPath (Join-Path $buildDirectory 'doorhandle-server') -Filter 'doorhandle-server-*.jar' -File)
    if ($jars.Count -ne 1 -or ($jars[0].Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw 'The fixed commit must produce exactly one regular server application jar.'
    }
    $jarDestination = Join-Path $artifactDirectory 'application.jar'
    if (Test-Path -LiteralPath $jarDestination) { throw 'Application artifact already exists; use a fresh build.' }
    Copy-Item -LiteralPath $jars[0].FullName -Destination $jarDestination
    $receipt['applicationJar'] = 'artifacts/application.jar'
    $receipt['applicationJarSha256'] = (Get-FileHash -LiteralPath $jarDestination -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt['applicationJarBytes'] = (Get-Item -LiteralPath $jarDestination).Length
    $receipt['status'] = 'PASS'
} catch {
    $receipt['errorType'] = $_.Exception.GetType().Name
    throw
} finally {
    $receipt['finishedAt'] = [DateTimeOffset]::UtcNow.ToString('o')
    $receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $artifactDirectory 'local-build.json') -Encoding utf8
}
