[CmdletBinding()]
param(
    [switch]$ExecuteLive,
    [ValidateSet('deepseek','dashscope')][string]$Provider = 'deepseek',
    [ValidateSet('routing','workbench')][string]$Suite = 'routing',
    [string]$WorkbenchMySqlConfig,
    [string]$MavenCommand
)
$ErrorActionPreference = 'Stop'
if (-not $ExecuteLive) {
    Write-Host 'This evaluation calls a paid provider with synthetic business data.'
    Write-Host 'Run with -ExecuteLive; -Suite routing executes ten fixed cases, workbench verifies plan/async-child lifecycle. No automatic retry or fallback.'
    exit 0
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if ($WorkbenchMySqlConfig -and $Suite -ne 'workbench') { throw 'WorkbenchMySqlConfig only applies to the workbench suite.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) { throw 'Selected provider credentials must already exist in the private project .env.' }
if (-not $MavenCommand) {
    $existing = Get-Command mvn.cmd -ErrorAction SilentlyContinue
    if ($existing) { $MavenCommand = $existing.Source }
    elseif (Test-Path -LiteralPath 'D:/ruanjian/apache-maven-3.9.6/bin/mvn.cmd') { $MavenCommand = 'D:/ruanjian/apache-maven-3.9.6/bin/mvn.cmd' }
    else { throw 'Supply an existing Maven command.' }
}
if (-not $env:JAVA_HOME -or -not (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin/java.exe'))) {
    if (Test-Path -LiteralPath 'C:/Program Files/Java/jdk-17/bin/java.exe') { $env:JAVA_HOME = 'C:/Program Files/Java/jdk-17' }
    else { throw 'An existing Java 17 installation is required.' }
}
$commit = (& git -C $projectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to identify the source commit.' }
$dirty = [bool](& git -C $projectRoot status --porcelain)
$runRoot = Join-Path $projectRoot ('work/agent-live-routing/' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
$buildRoot = Join-Path $runRoot 'build'
$outputRoot = Join-Path $runRoot 'experiment'
New-Item -ItemType Directory -Path $buildRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'pom.xml') -Destination $buildRoot
# An independent source snapshot avoids IDE incremental classes. Never copy
# .env, runtime directories, binaries, model weights, or deployment credentials.
$modules = Get-ChildItem -LiteralPath $projectRoot -Directory | Where-Object { $_.Name -like 'doorhandle-*' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'pom.xml')) }
foreach ($module in $modules) {
    $targetModule = Join-Path $buildRoot $module.Name
    New-Item -ItemType Directory -Path $targetModule | Out-Null
    Copy-Item -LiteralPath (Join-Path $module.FullName 'pom.xml') -Destination $targetModule
    $source = Join-Path $module.FullName 'src'
    if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $targetModule -Recurse }
}
New-Item -ItemType Directory -Path (Join-Path $buildRoot 'eval') | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'eval/agent') -Destination (Join-Path $buildRoot 'eval') -Recurse
$testClass = if ($Suite -eq 'workbench') { 'AgentWorkbenchLiveEvalTest' } else { 'AgentLiveRoutingEvalTest' }
$enableProperty = if ($Suite -eq 'workbench') { '-Dagent.workbench.live=true' } else { '-Dagent.routing.live=true' }
$arguments = @('-B','-f',(Join-Path $buildRoot 'pom.xml'),'-pl','doorhandle-module-ai','-am','test',
    "-Dtest=$testClass",'-Dsurefire.failIfNoSpecifiedTests=false',$enableProperty,
    "-Dagent.routing.project=$projectRoot","-Dagent.routing.output=$outputRoot","-Dagent.routing.provider=$Provider",
    "-Dagent.routing.commit=$commit","-Dagent.routing.dirty=$($dirty.ToString().ToLowerInvariant())")
if ($WorkbenchMySqlConfig) { $arguments += "-Dagent.workbench.mysqlConfig=$((Resolve-Path -LiteralPath $WorkbenchMySqlConfig).Path)" }
& $MavenCommand @arguments *> (Join-Path $runRoot 'maven.log')
$buildExit = $LASTEXITCODE
$reportPath = Join-Path $outputRoot 'report.json'
if (-not (Test-Path -LiteralPath $reportPath)) { Write-Host "No live report produced. Inspect $runRoot/maven.log"; exit 1 }
$report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Suite -eq 'workbench') {
    Write-Host "Live workbench: gate=$($report.gatePassed); checks=$(@($report.checks).Count); database=$($report.databaseKind); provider=$($report.modelId); model requests=$($report.modelRequests)"
} else {
    $passed = @($report.results | Where-Object { $_.status -eq 'PASS' }).Count
    Write-Host "Live routing: $passed/$($report.declaredCases) passed; provider $($report.modelId); model requests $($report.modelRequests)"
}
Write-Host "Private report: $reportPath"
Write-Host 'Rule results are not human quality approval, production business authorization, or a bill.'
if ($buildExit -ne 0 -or -not $report.gatePassed) { Write-Host 'Evaluation incomplete or failed. Inspect evidence; do not automatically repeat paid requests.'; exit 1 }
exit 0
