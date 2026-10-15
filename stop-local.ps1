[CmdletBinding()]
param([switch]$ApplicationsOnly)
& (Join-Path $PSScriptRoot 'script/shell/stop-local-project.ps1') @PSBoundParameters
