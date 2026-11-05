[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$PythonArguments
)

$ErrorActionPreference = 'Stop'
throw 'Runtime and tests are ECS-only. This Windows wrapper is retired; use docs/ECS-only-runtime.md. Local editing/build tools must be invoked explicitly.'
