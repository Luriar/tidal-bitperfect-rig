param(
    [switch]$NoPip,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CamillaSrc = Join-Path $RepoRoot "camilladsp"
$EqSrc = Join-Path $RepoRoot "eq"
$LightSrc = Join-Path $RepoRoot "light-host"
$CamillaDst = "C:\CamillaDSP"
$EqDst = "C:\EQ"
$Startup = [Environment]::GetFolderPath("Startup")

function Step([string]$m) { Write-Host ("[+] " + $m) -ForegroundColor Cyan }
function Warn([string]$m) { Write-Host ("[!] " + $m) -ForegroundColor Yellow }
function Ok([string]$m) { Write-Host ("[OK] " + $m) -ForegroundColor Green }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw "Run this script from an elevated Administrator PowerShell."
}

Step "Stop custom audio processes before restoring files"
Get-Process -Name "camilladsp","Light Host" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Step "Restore repository-managed files"
New-Item -ItemType Directory -Force -Path $CamillaDst,$EqDst | Out-Null
Copy-Item (Join-Path $CamillaSrc "*") $CamillaDst -Recurse -Force
Copy-Item (Join-Path $EqSrc "*") $EqDst -Recurse -Force
if (Test-Path (Join-Path $LightSrc "light-host-autostart.ps1")) {
    Copy-Item (Join-Path $LightSrc "light-host-autostart.ps1") (Join-Path $EqDst "light-host-autostart.ps1") -Force
    Copy-Item (Join-Path $LightSrc "light-host-autostart.vbs") (Join-Path $EqDst "light-host-autostart.vbs") -Force
}

Step "Restore W80 as the default profile"
Copy-Item (Join-Path $CamillaDst "music_w80.yml") (Join-Path $CamillaDst "config_template.yml") -Force
Set-Content -LiteralPath (Join-Path $EqDst "current_m4.txt") -Value "# M4 default profile (restored by restore_this_pc.ps1)`r`nInclude: W80_Monitoring.txt" -Encoding UTF8

Step "Restore Light Host settings snapshot"
$lhSettingsDir = Join-Path $env:APPDATA "Light Host"
New-Item -ItemType Directory -Force -Path $lhSettingsDir | Out-Null
if (Test-Path (Join-Path $LightSrc "Light Host.settings")) {
    Copy-Item (Join-Path $LightSrc "Light Host.settings") (Join-Path $lhSettingsDir "Light Host.settings") -Force
}

if (-not $NoPip) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Step "Install/repair Python dependencies"
        & py -3 -m pip install --disable-pip-version-check sounddevice numpy websocket-client winsdk
        if ($LASTEXITCODE -ne 0) { Warn "pip dependency install returned exit code $LASTEXITCODE" }
    } else {
        Warn "Python launcher 'py' not found; install Python 3.12 then run pip command from README."
    }
}

Step "Register logon autostart"
Copy-Item (Join-Path $CamillaDst "camilla_autostart.vbs") (Join-Path $Startup "camilla_autostart.vbs") -Force
if (Test-Path (Join-Path $EqDst "light-host-autostart.vbs")) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut((Join-Path $Startup "Light Host.lnk"))
    $sc.TargetPath = Join-Path $env:WINDIR "System32\wscript.exe"
    $sc.Arguments = '"C:\EQ\light-host-autostart.vbs"'
    $sc.WorkingDirectory = $EqDst
    $sc.Save()
}

Step "Wire Equalizer APO master config when installed"
$eqApoConfig = "C:\Program Files\EqualizerAPO\config\config.txt"
if (Test-Path (Split-Path $eqApoConfig -Parent)) {
    Set-Content -LiteralPath $eqApoConfig -Value "Include: C:\EQ\eqapo_master.txt" -Encoding UTF8
} else {
    Warn "Equalizer APO not found. Install it, select the real listening endpoint(s), then re-run this script."
}

Step "Validate core prerequisites"
$checks = @(
    @{ Name="CamillaDSP ASIO binary"; Path="C:\CamillaDSP\camilladsp.exe" },
    @{ Name="Virtual Audio Cable control panel"; Path="C:\Program Files\Virtual Audio Cable\vcctlpan.exe" },
    @{ Name="Light Host 1.2.1"; Path="C:\Program Files\Light Host 1.2.1 Win64\Light Host.exe" },
    @{ Name="TIDAL"; Path=(Join-Path $env:LOCALAPPDATA "TIDAL") }
)
$missing = @()
foreach ($c in $checks) {
    if (Test-Path $c.Path) { Ok $c.Name } else { Warn ($c.Name + " missing: " + $c.Path); $missing += $c.Name }
}
$motu = Get-PnpDevice -Class MEDIA -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -eq "MOTU M Series" -and $_.Status -eq "OK" } | Select-Object -First 1
if ($motu) { Ok "MOTU M Series driver/device" } else { Warn "MOTU M Series driver/device not ready"; $missing += "MOTU M Series" }
$vb = Get-PnpDevice -Class AudioEndpoint -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -eq "CABLE Input(VB-Audio Virtual Cable)" -and $_.Status -eq "OK" } | Select-Object -First 1
if ($vb) { Ok "VB-Audio Virtual Cable endpoint" } else { Warn "VB-Audio Virtual Cable endpoint not ready"; $missing += "VB-Audio Virtual Cable" }

if (Get-Command py -ErrorAction SilentlyContinue) {
    Step "Compile-check supervisor"
    & py -3 -m py_compile (Join-Path $CamillaDst "supervisor.py")
    if ($LASTEXITCODE -ne 0) { throw "supervisor.py compile check failed" }
    Ok "supervisor.py syntax"
}

if (-not $NoStart -and $missing.Count -eq 0) {
    Step "Start restored launchers"
    Start-Process (Join-Path $env:WINDIR "System32\wscript.exe") -ArgumentList ('"' + (Join-Path $Startup "camilla_autostart.vbs") + '"')
    if (Test-Path (Join-Path $Startup "Light Host.lnk")) { Start-Process (Join-Path $Startup "Light Host.lnk") }
} elseif ($missing.Count -gt 0) {
    Warn "Custom configuration is restored, but third-party prerequisites above must be installed before the chain can run."
}

Write-Host ""
Ok "Repository-managed restore finished."
Write-Host "Manual post-format checks still required:"
Write-Host "  1) TIDAL output = Line 1(Virtual Audio Cable), Exclusive ON"
Write-Host "  2) VAC cable format range / volume-control / channel-mixing settings"
Write-Host "  3) Equalizer APO Configurator: real listening endpoint only (never Line 1/CABLE)"
Write-Host "  4) Exact Light Host plugin chain requires the same VST/VST3 plug-ins to be reinstalled"
Write-Host "No reboot was performed."
