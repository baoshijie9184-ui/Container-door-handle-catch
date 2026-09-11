[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$PythonArguments
)

$EnvironmentName = 'leetcode'
$condaCommand = Get-Command conda -ErrorAction SilentlyContinue

if (-not $condaCommand) {
    Write-Error "Conda was not found. Install Conda and create the '$EnvironmentName' environment."
    exit 127
}

try {
    $environmentJson = & conda env list --json
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'Unable to read the Conda environment list.'
        exit $LASTEXITCODE
    }
    $environmentData = $environmentJson | ConvertFrom-Json
} catch {
    Write-Error "Unable to inspect Conda environments: $($_.Exception.Message)"
    exit 2
}

$environmentExists = @($environmentData.envs) | Where-Object {
    [IO.Path]::GetFileName($_.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)) -eq $EnvironmentName
}

if (-not $environmentExists) {
    Write-Error "Conda environment '$EnvironmentName' was not found. Run: conda env create -f environment.yml"
    exit 2
}

& conda run --no-capture-output -n $EnvironmentName python @PythonArguments
exit $LASTEXITCODE
