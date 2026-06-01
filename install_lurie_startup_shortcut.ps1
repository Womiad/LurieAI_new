param(
    [string]$ProjectRoot = $PSScriptRoot,
    [string]$ShortcutName = "LurieAI Startup.lnk"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$StartupScript = Join-Path $ProjectRoot "start_lurie_stack.ps1"

if (-not (Test-Path -LiteralPath $StartupScript)) {
    throw "Cannot find startup script: $StartupScript"
}

$StartupFolder = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupFolder $ShortcutName

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$StartupScript`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.WindowStyle = 1
$Shortcut.Description = "Start VTube Studio, Discord, and Lurie Discord bot."
$Shortcut.Save()

Write-Host "Installed startup shortcut:"
Write-Host $ShortcutPath
