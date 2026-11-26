param(
    [switch] $DryRun,
    [switch] $KeepIntegrations,
    [switch] $Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [object[]] $RemainingArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PackageName = "modelglot"
$ModelGlotHomeDirname = ".modelglot"
$ModelGlotAppUserModelId = "io.github.amedeo82.modelglot"
$ModelGlotCommands = @(
    "modelglot-desktop",
    "modelglot-server",
    "modelglot-claude",
    "modelglot-codex",
    "modelglot-pi",
    "modelglot-opencode",
    "modelglot-cline",
    "modelglot-hermes",
    "modelglot-dsh",
    "modelglot-grok",
    "modelglot-muse",
    "modelglot-aider",
    "modelglot-agy",
    "modelglot-doctor",
    "modelglot-update",
    "modelglot-init"
)
$script:UvPath = ""
$script:UvToolBin = ""

function Show-Usage {
    @"
Usage: uninstall.ps1 [options]

Removes the ModelGlot uv tools, then deletes ~/.modelglot/ after removal is verified.
Does not remove uv, Claude Code, Codex, Pi, OpenCode, Cline, Hermes Agent, DeepSeek Harness, Grok Build, Muse Code, Aider, Antigravity CLI, the uv-managed Python runtime, or shared PATH entries.

Options:
  -DryRun                Print commands without running them.
  -KeepIntegrations      Leave editor/app integrations unchanged.
  -Help                  Show this help text.
"@
}

function Write-Step {
    param([string] $Message)

    Write-Host ""
    Write-Host "==> $Message"
}

function Format-Argument {
    param([string] $Value)

    if ($Value -match '^[A-Za-z0-9_./:@%+=,\[\]\\-]+$') {
        return $Value
    }
    return "'" + ($Value -replace "'", "''") + "'"
}

function Format-Command {
    param(
        [string] $FilePath,
        [string[]] $Arguments = @()
    )

    $parts = @($FilePath) + $Arguments
    return ($parts | ForEach-Object { Format-Argument ([string] $_) }) -join " "
}

function Get-ApplicationCommand {
    param([string] $Name)

    $commands = @(Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue)
    if ($commands.Count -eq 0) {
        return $null
    }
    return $commands[0]
}

function Invoke-NativeResult {
    param(
        [string] $FilePath,
        [string[]] $Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $global:LASTEXITCODE = 0
        $output = (& $FilePath @Arguments 2>&1 | Out-String).Trim()
        return [pscustomobject] @{
            ExitCode = $LASTEXITCODE
            Output = $output
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Test-MissingUvToolError {
    param(
        [string] $Output,
        [string] $PackageName
    )

    $normalized = $Output.ToLowerInvariant()
    return $normalized.Contains($PackageName) -and $normalized.Contains("is not installed")
}

function Add-PathEntry {
    param([string] $PathEntry)

    if ([string]::IsNullOrWhiteSpace($PathEntry)) {
        return
    }
    $separator = [IO.Path]::PathSeparator
    $entries = @()
    if (-not [string]::IsNullOrEmpty($env:Path)) {
        $entries = $env:Path -split [regex]::Escape([string] $separator)
    }
    if ($entries -notcontains $PathEntry) {
        $env:Path = "$PathEntry$separator$env:Path"
    }
}

function Add-KnownUvPaths {
    Add-PathEntry (Join-Path $env:USERPROFILE ".local\bin")
    Add-PathEntry (Join-Path $env:USERPROFILE ".cargo\bin")
}

function Assert-NoModelGlotProcessesRunning {
    $running = @()
    foreach ($commandName in $ModelGlotCommands) {
        $processes = @(Get-Process -Name $commandName -ErrorAction SilentlyContinue)
        if ($processes.Count -gt 0) {
            $running += $commandName
        }
    }
    if ($running.Count -gt 0) {
        throw "ModelGlot is still running ($($running -join ', ')). Stop those processes, then rerun uninstall."
    }
}

function Initialize-UvContext {
    Add-KnownUvPaths

    if ($DryRun) {
        Write-Host "+ uv tool dir --bin"
        return
    }

    $uvCommand = Get-ApplicationCommand "uv"
    if (-not $uvCommand) {
        throw "uv is required to remove the ModelGlot tool. Install uv, then rerun this uninstaller; ~/.modelglot was not deleted."
    }
    $script:UvPath = $uvCommand.Source

    $commandText = Format-Command -FilePath $script:UvPath -Arguments @("tool", "dir", "--bin")
    Write-Host "+ $commandText"
    $result = Invoke-NativeResult -FilePath $script:UvPath -Arguments @("tool", "dir", "--bin")
    if ($result.ExitCode -ne 0) {
        if (-not [string]::IsNullOrWhiteSpace($result.Output)) {
            [Console]::Error.WriteLine($result.Output)
        }
        throw "Could not determine the uv tool bin directory (exit code $($result.ExitCode)); ~/.modelglot was not deleted."
    }
    $script:UvToolBin = $result.Output.Trim()
    if ([string]::IsNullOrWhiteSpace($script:UvToolBin)) {
        throw "uv returned an empty tool bin directory; ~/.modelglot was not deleted."
    }
}

function Uninstall-UvTool {
    param([string] $PackageName)

    Write-Host "+ uv tool uninstall $PackageName"
    if ($DryRun) {
        return
    }

    $result = Invoke-NativeResult -FilePath $script:UvPath -Arguments @(
        "tool",
        "uninstall",
        $PackageName
    )
    if ($result.ExitCode -eq 0) {
        if (-not [string]::IsNullOrWhiteSpace($result.Output)) {
            Write-Host $result.Output
        }
        return
    }
    if (Test-MissingUvToolError -Output $result.Output -PackageName $PackageName) {
        Write-Host "$PackageName uv tool is already absent; continuing with entry point verification."
        return
    }
    if (-not [string]::IsNullOrWhiteSpace($result.Output)) {
        [Console]::Error.WriteLine($result.Output)
    }
    throw "uv tool uninstall $PackageName failed with exit code $($result.ExitCode); ~/.modelglot was not deleted."
}

function Uninstall-ModelGlot {
    Uninstall-UvTool -PackageName $PackageName
}

function Disconnect-ModelGlotIntegrations {
    if ($KeepIntegrations) {
        return
    }
    if ($DryRun) {
        Write-Host "+ modelglot-doctor --disconnect-integrations"
        return
    }
    $doctorPath = $null
    foreach ($extension in @(".exe", ".cmd", ".bat", "")) {
        $candidate = Join-Path $script:UvToolBin "modelglot-doctor$extension"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $doctorPath = $candidate
            break
        }
    }
    if (-not $doctorPath) {
        throw "ModelGlot's integration cleanup command is unavailable. Update ModelGlot first, or disconnect editor/app integrations manually and rerun with -KeepIntegrations. ModelGlot data was not deleted."
    }
    Write-Host "+ $(Format-Command -FilePath $doctorPath -Arguments @('--disconnect-integrations'))"
    $result = Invoke-NativeResult -FilePath $doctorPath -Arguments @("--disconnect-integrations")
    if (-not [string]::IsNullOrWhiteSpace($result.Output)) {
        Write-Host $result.Output
    }
    if ($result.ExitCode -ne 0) {
        throw "Editor/app integration cleanup failed. Correct the reported problem and retry. For older ModelGlot versions, update first or disconnect manually and rerun with -KeepIntegrations. ModelGlot and its data were not deleted."
    }
}

function Confirm-ModelGlotCommandsRemoved {
    if ($DryRun) {
        Write-Host "+ verify all ModelGlot entry points are absent from the uv tool bin directory"
        return
    }

    $remaining = @()
    $extensions = @("", ".exe", ".cmd", ".bat", ".ps1")
    foreach ($commandName in $ModelGlotCommands) {
        foreach ($extension in $extensions) {
            $commandPath = Join-Path $script:UvToolBin "$commandName$extension"
            if (Test-Path -LiteralPath $commandPath) {
                $remaining += $commandPath
            }
        }
    }
    if ($remaining.Count -gt 0) {
        throw "ModelGlot entry points remain after uv uninstall: $($remaining -join ', '); ~/.modelglot was not deleted."
    }
}

function Test-EquivalentPath {
    param(
        [string] $Left,
        [string] $Right
    )

    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) {
        return $false
    }
    try {
        return [string]::Equals(
            [IO.Path]::GetFullPath($Left),
            [IO.Path]::GetFullPath($Right),
            [StringComparison]::OrdinalIgnoreCase
        )
    }
    catch {
        return $false
    }
}

function Test-ModelGlotDesktopShortcutTarget {
    param([string] $TargetPath)

    foreach ($extension in @("", ".exe", ".cmd", ".bat", ".ps1")) {
        $expectedTarget = Join-Path $script:UvToolBin "modelglot-desktop$extension"
        if (Test-EquivalentPath -Left $TargetPath -Right $expectedTarget) {
            return $true
        }
    }
    return $false
}

function Remove-ModelGlotDesktopShortcuts {
    $shortcutPaths = @(
        (Join-Path $env:USERPROFILE "Desktop\ModelGlot.lnk"),
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ModelGlot.lnk")
    )
    $shell = New-Object -ComObject WScript.Shell
    foreach ($shortcutPath in $shortcutPaths) {
        if (-not (Test-Path -LiteralPath $shortcutPath)) {
            continue
        }
        try {
            $shortcut = $shell.CreateShortcut($shortcutPath)
            $isModelGlotShortcut = Test-ModelGlotDesktopShortcutTarget -TargetPath $shortcut.TargetPath
        }
        catch {
            $isModelGlotShortcut = $false
        }
        if (-not $isModelGlotShortcut) {
            Write-Host "A shortcut not managed by ModelGlot exists at $shortcutPath; leaving it unchanged."
            continue
        }
        Write-Host "+ Remove-Item -LiteralPath $(Format-Argument $shortcutPath) -Force"
        if (-not $DryRun) {
            Remove-Item -LiteralPath $shortcutPath -Force
        }
    }
}

function Remove-ModelGlotAppUserModelId {
    $registryPath = "Registry::HKEY_CURRENT_USER\Software\Classes\AppUserModelId\$ModelGlotAppUserModelId"
    if (-not (Test-Path -LiteralPath $registryPath)) {
        return
    }
    Write-Host "+ Remove-Item -LiteralPath $(Format-Argument $registryPath) -Force"
    if (-not $DryRun) {
        Remove-Item -LiteralPath $registryPath -Force
    }
}

function Purge-ModelGlotHome {
    $modelglotHome = Join-Path $env:USERPROFILE $ModelGlotHomeDirname
    if (-not (Test-Path -LiteralPath $modelglotHome)) {
        Write-Host "No ModelGlot config directory at $modelglotHome; skipping purge."
        return
    }

    $commandText = @(
        "Remove-Item",
        "-LiteralPath",
        (Format-Argument $modelglotHome),
        "-Recurse",
        "-Force"
    ) -join " "
    Write-Host "+ $commandText"
    if ($DryRun) {
        return
    }

    Remove-Item -LiteralPath $modelglotHome -Recurse -Force
    if (Test-Path -LiteralPath $modelglotHome) {
        throw "ModelGlot config directory still exists after deletion: $modelglotHome"
    }
}

if ($Help) {
    Show-Usage
    return
}
if ($RemainingArgs.Count -gt 0) {
    Show-Usage
    throw "Unknown option: $($RemainingArgs -join ' ')"
}
if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
    throw "USERPROFILE is not set; cannot locate ModelGlot data."
}

Write-Step "Checking for running ModelGlot processes"
Assert-NoModelGlotProcessesRunning

Write-Step "Locating the uv-managed ModelGlot installation"
Initialize-UvContext

Write-Step "Disconnecting ModelGlot editor/app integrations"
Disconnect-ModelGlotIntegrations

Write-Step "Removing ModelGlot uv tools"
Uninstall-ModelGlot

Write-Step "Verifying ModelGlot entry points were removed"
Confirm-ModelGlotCommandsRemoved

Write-Step "Removing ModelGlot desktop shortcuts"
Remove-ModelGlotDesktopShortcuts

Write-Step "Removing ModelGlot notification identities"
Remove-ModelGlotAppUserModelId

Write-Step "Purging ModelGlot config and data from ~/.modelglot"
Purge-ModelGlotHome

Write-Host ""
if ($DryRun) {
    Write-Host "Dry run complete. No changes were made."
}
else {
    Write-Host "ModelGlot has been removed and verified."
    Write-Host "uv, Claude Code, Codex, Pi, OpenCode, Cline, Hermes Agent, DeepSeek Harness, Grok Build, Muse Code, Aider, the uv-managed Python runtime, and shared PATH entries were left installed."
}
