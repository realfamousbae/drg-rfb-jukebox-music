<#
.SYNOPSIS
  Windows PC: prepare tracks -> import into UE 4.27 -> cook -> collect -> pack -> zip for mod.io.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\build.ps1 -Project C:\Mods\Audio-Modding-Template\FSD.uproject

  Close the Unreal Editor first: the import and cook steps run it headless.
  Use -SkipPrepare / -SkipImport / -SkipCook to resume from a later step.
#>
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$UERoot = "",
    [string]$ModName = "RFB_Jukebox",
    [string]$Repak = "repak",
    [string]$Python = "python",
    [double]$TargetLufs = -11,
    [switch]$TrimSilence,
    [switch]$SkipPrepare,
    [switch]$SkipImport,
    [switch]$SkipCook
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Project = (Resolve-Path $Project).Path
if (-not $UERoot) {
    # Wherever the Epic Games Launcher installed UE 4.27 (any drive), else the launcher's default folder.
    $UERoot = Get-ChildItem "$env:ProgramData\Epic\EpicGamesLauncher\Data\Manifests" -Filter *.item -ErrorAction SilentlyContinue |
        ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json } |
        Where-Object { $_.AppName -eq "UE_4.27" } | Select-Object -First 1 -ExpandProperty InstallLocation
    if (-not $UERoot) { $UERoot = "C:\Program Files\Epic Games\UE_4.27" }
}
Write-Host "UE 4.27: $UERoot"
$Editor = Join-Path $UERoot "Engine\Binaries\Win64\UE4Editor-Cmd.exe"
$RunUAT = Join-Path $UERoot "Engine\Build\BatchFiles\RunUAT.bat"
$PakDir = Join-Path $Repo "pak\${ModName}_P"
$Dist = Join-Path $Repo "dist"

function Step($name) { Write-Host "`n=== $name ===" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

if ($Repo -match " ") { throw "Move the repo to a path without spaces (UE command-line parsing breaks): $Repo" }
foreach ($tool in @($Editor, $RunUAT)) { if (-not (Test-Path $tool)) { throw "Not found: $tool (check -UERoot)" } }

Push-Location $Repo
try {
    if (-not $SkipPrepare) {
        Step "Prepare tracks"
        $prep = @("tools\prepare_tracks.py", "build", "--target-lufs", "$TargetLufs")
        if ($TrimSilence) { $prep += "--trim-silence" }
        & $Python @prep; Check "prepare_tracks.py"
    }

    if (-not $SkipImport) {
        Step "Import into UE"
        $env:RFB_REPO = $Repo
        & $Editor $Project -run=pythonscript "-script=$Repo\tools\ue_import.py" -unattended -nop4 -nosplash
        Check "ue_import.py"
    }

    if (-not $SkipCook) {
        Step "Cook (WindowsNoEditor)"
        # RunUAT.bat calls AutomationTool.exe from its own folder without .\ - breaks when this is set.
        Remove-Item Env:NoDefaultCurrentDirectoryInExePath -ErrorAction SilentlyContinue
        & $RunUAT BuildCookRun "-project=$Project" -noP4 -platform=Win64 -clientconfig=Shipping `
            -cook -cookall -skipstage -nocompileeditor -unattended -utf8output
        Check "cook"
    }

    Step "Collect cooked jukebox assets"
    $Cooked = Join-Path (Split-Path $Project) "Saved\Cooked\WindowsNoEditor"
    & $Python tools\collect_cooked.py --cooked $Cooked --layout repak --out $PakDir --clean
    Check "collect_cooked.py"

    Step "Pack"
    New-Item -ItemType Directory -Force $Dist | Out-Null
    $Pak = Join-Path $Dist "${ModName}_P.pak"
    & $Repak pack --version V11 $PakDir $Pak; Check "repak"
    $Zip = Join-Path $Dist "$ModName.zip"
    Compress-Archive -Path $Pak -DestinationPath $Zip -Force

    Step "Done"
    Write-Host "pak: $Pak"
    Write-Host "zip for mod.io: $Zip"
}
finally {
    Pop-Location
}
