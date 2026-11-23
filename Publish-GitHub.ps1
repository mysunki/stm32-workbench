param(
    [string]$Owner = 'mysunki',
    [string]$Name = 'stm32-workbench',
    [ValidateSet('public', 'private')][string]$Visibility = 'public'
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
if ($Owner -notmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,38}$' -or $Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$') {
    throw 'Invalid GitHub owner or repository name.'
}
foreach ($toolName in @('python', 'git', 'gh')) {
    if (-not (Get-Command $toolName -ErrorAction SilentlyContinue)) {
        throw "Missing $toolName. Install it on your own PC before publishing. No installation was attempted."
    }
}

$account = & gh api user --jq '.login'
if ($LASTEXITCODE -ne 0) { throw 'GitHub authentication unavailable. Run gh auth login on your PC, then retry.' }
if ($account.Trim() -ne $Owner) { throw "Authenticated account is $account; expected $Owner. No repository was created." }
$repository = "$Owner/$Name"
# Windows PowerShell 5.1 turns native stderr into a terminating error under Stop,
# even when a missing repository is the expected nonzero result. Handle that result
# locally, then restore normal error handling before any publication work.
$lookupErrorPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & gh repo view $repository --json nameWithOwner 2>$null | Out-Null
    $repositoryLookupExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $lookupErrorPreference
}
if ($repositoryLookupExitCode -eq 0) { throw "$repository already exists. This helper will not overwrite or push to an existing repository." }

$verificationRoot = Join-Path $projectRoot ('local/before-publication-' + [guid]::NewGuid().ToString('N'))
& python -I -B (Join-Path $projectRoot 'tools/verify_from_scratch.py') --output $verificationRoot
if ($LASTEXITCODE -ne 0) { throw 'Fresh-environment desktop acceptance failed. Publication stopped.' }
# Publish precisely the source snapshot used by the actual desktop acceptance run.
$projectRoot = [IO.Path]::GetFullPath((Join-Path $verificationRoot 'source'))
$manifestJson = & python -I -B (Join-Path $projectRoot 'tools/package_source.py') --list
if ($LASTEXITCODE -ne 0) { throw 'Source audit failed. Publication stopped.' }
$sourceFiles = @($manifestJson | ConvertFrom-Json)
if ($sourceFiles.Count -lt 10) { throw 'Unexpectedly small source manifest. Publication stopped.' }

# A fresh staging checkout prevents parent files and existing Git history from being pushed.
$publishRoot = Join-Path ([IO.Path]::GetTempPath()) ('stm32-workbench-publish-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $publishRoot | Out-Null
foreach ($relativePath in $sourceFiles) {
    $sourcePath = [IO.Path]::GetFullPath((Join-Path $projectRoot $relativePath))
    $destinationPath = [IO.Path]::GetFullPath((Join-Path $publishRoot $relativePath))
    if (-not $sourcePath.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        -not $destinationPath.StartsWith($publishRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Manifest path escapes the selected project. Publication stopped.'
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destinationPath) -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
}

Push-Location -LiteralPath $publishRoot
try {
    & python -I -B tools/package_source.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Staged source audit failed.' }
    & git init -b main
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize the staged source repository.' }
    foreach ($relativePath in $sourceFiles) {
        & git add -- $relativePath
        if ($LASTEXITCODE -ne 0) { throw "Could not stage $relativePath" }
    }
    & git -c "user.name=$Owner" -c "user.email=$Owner@users.noreply.github.com" commit -m 'Build independent multi-board STM32 observation workbench'
    if ($LASTEXITCODE -ne 0) { throw 'Could not commit the staged source.' }
    & gh repo create $repository "--$Visibility" --source $publishRoot --remote origin --push --description 'Multi-board STM32 variable observation, firmware inspection, and offline session replay.'
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub publication failed. Staging checkout preserved at $publishRoot. Check GitHub for partial creation before retrying."
    }
    & gh repo view $repository --json url --jq '.url'
    if ($LASTEXITCODE -ne 0) { throw 'Push completed, but final URL verification failed. Check GitHub before retrying.' }
    Write-Output "Source checkout retained at $publishRoot for future Git operations."
}
finally {
    Pop-Location
}
