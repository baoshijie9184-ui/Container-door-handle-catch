[CmdletBinding()]
param(
    [string]$MavenCommand,
    [string]$Baseline
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$outputRoot = Join-Path $projectRoot ('work/agent-eval/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,6))
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

if (-not $MavenCommand) {
    $maven = Get-Command mvn.cmd -ErrorAction SilentlyContinue
    if ($maven) { $MavenCommand = $maven.Source }
    elseif (Test-Path -LiteralPath 'D:/ruanjian/apache-maven-3.9.6/bin/mvn.cmd') { $MavenCommand = 'D:/ruanjian/apache-maven-3.9.6/bin/mvn.cmd' }
    else { throw 'Maven not found. Supply -MavenCommand or use the existing Maven installation.' }
}
$javaCandidate = if ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME 'bin/java.exe' } else { $null }
if (-not $javaCandidate -or -not (Test-Path -LiteralPath $javaCandidate)) {
    if (Test-Path -LiteralPath 'C:/Program Files/Java/jdk-17/bin/java.exe') { $env:JAVA_HOME = 'C:/Program Files/Java/jdk-17' }
    else { throw 'An existing Java 17 or later installation is required.' }
}
if ($Baseline) { $Baseline = (Resolve-Path -LiteralPath $Baseline).Path }
$commit = (& git -C $projectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to read project Git commit.' }
$dirty = [bool](& git -C $projectRoot status --porcelain)
$arguments = @('-B','-pl','doorhandle-module-ai','-am','test',
    '-Dtest=AgentContractEvalTest,AgentEvalRulesTest','-Dsurefire.failIfNoSpecifiedTests=false',
    "-Dagent.eval.project=$projectRoot", "-Dagent.eval.output=$outputRoot", "-Dagent.eval.commit=$commit",
    "-Dagent.eval.dirty=$($dirty.ToString().ToLowerInvariant())")
if ($Baseline) { $arguments += "-Dagent.eval.baseline=$Baseline" }
Push-Location $projectRoot
try {
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $MavenCommand @arguments *> (Join-Path $outputRoot 'maven.log')
    $buildExit = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorPreference
} finally { Pop-Location }

$reportPath = Join-Path $outputRoot 'report.json'
if (-not (Test-Path -LiteralPath $reportPath)) {
    Write-Host "Evaluation did not produce a report. Inspect: $outputRoot/maven.log"
    exit 1
}
$report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "Agent contract evaluation: $($report.summary.counts.PASS)/$($report.summary.total) passed"
Write-Host "Mode: $($report.metadata.mode)"
Write-Host "Report: $reportPath"
Write-Host "Summary: $outputRoot/report.md"
Write-Host 'This run does not evaluate paid models or approve production release.'
$gate = $report.experimentGatePassed
if ($Baseline) { $gate = $gate -and $report.baselineComparison.compatible -and $report.baselineComparison.noRegressions }
if ($buildExit -ne 0 -or -not $gate) {
    Write-Host 'Evaluation gate: BLOCKED. Inspect the report and Maven log for rule failures, missing cases or incompatible baseline.'
    exit 1
}
Write-Host 'Evaluation gate: PASSED (offline contract rules only).'
exit 0
