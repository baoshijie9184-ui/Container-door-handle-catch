[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$KafkaHome,
    [string]$JavaHome,
    [string]$MySqlService,
    [string]$RedisService,
    [switch]$BuildBackend,
    [switch]$NoAgentUI,
    [switch]$NoFrontend,
    [switch]$OpenBrowser
)
& (Join-Path $PSScriptRoot 'script/shell/start-local-project.ps1') @PSBoundParameters
