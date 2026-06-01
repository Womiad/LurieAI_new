param(
    [string]$ProjectRoot = $PSScriptRoot,
    [switch]$SkipVTubeStudio,
    [switch]$SkipDiscord
)

$ErrorActionPreference = "Stop"

function Start-OptionalProcess {
    param(
        [string]$Name,
        [string]$Path,
        [string]$ArgumentList,
        [string]$FallbackUri
    )

    if ($Path -and (Test-Path -LiteralPath $Path)) {
        Write-Host "Starting $Name from $Path"
        Start-Process -FilePath $Path -ArgumentList $ArgumentList
        return
    }

    if ($FallbackUri) {
        Write-Host "Starting $Name from $FallbackUri"
        Start-Process $FallbackUri
        return
    }

    Write-Warning "$Name path not found and no fallback URI is configured."
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$BotEntry = Join-Path $ProjectRoot "LurieBot_a1.py"
$ActivateScript = Join-Path $ProjectRoot "venv\Scripts\Activate.ps1"

if (-not (Test-Path -LiteralPath $BotEntry)) {
    throw "Cannot find bot entry: $BotEntry"
}

if (-not (Test-Path -LiteralPath $ActivateScript)) {
    throw "Cannot find virtual environment activate script: $ActivateScript"
}

if (-not $SkipVTubeStudio) {
    $VTubeStudioPath = $env:VTUBE_STUDIO_PATH
    Start-OptionalProcess `
        -Name "VTube Studio" `
        -Path $VTubeStudioPath `
        -ArgumentList "" `
        -FallbackUri "steam://rungameid/1325860"
}

if (-not $SkipDiscord) {
    $DiscordPath = $env:DISCORD_PATH
    if (-not $DiscordPath) {
        $DefaultDiscordUpdater = Join-Path $env:LOCALAPPDATA "Discord\Update.exe"
        if (Test-Path -LiteralPath $DefaultDiscordUpdater) {
            $DiscordPath = $DefaultDiscordUpdater
        }
    }

    if ($DiscordPath -and ($DiscordPath.EndsWith("Update.exe", [System.StringComparison]::OrdinalIgnoreCase))) {
        Start-OptionalProcess `
            -Name "Discord" `
            -Path $DiscordPath `
            -ArgumentList "--processStart Discord.exe" `
            -FallbackUri "discord://-/"
    }
    else {
        Start-OptionalProcess `
            -Name "Discord" `
            -Path $DiscordPath `
            -ArgumentList "" `
            -FallbackUri "discord://-/"
    }
}

$BotCommand = @"
Set-Location -LiteralPath '$ProjectRoot'
`$env:PYTHONUTF8 = '1'
. '$ActivateScript'
python '$BotEntry'
"@

Write-Host "Starting Lurie Discord bot in virtual environment..."
Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $BotCommand) `
    -WorkingDirectory $ProjectRoot

Write-Host "Startup sequence launched. The bot will preload the background model and generate the first background after Discord login."
