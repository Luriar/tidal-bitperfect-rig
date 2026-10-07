$ErrorActionPreference = "SilentlyContinue"
$exe = "C:\Program Files\Light Host 1.2.1 Win64\Light Host.exe"
$log = "C:\EQ\light-host-autostart.log"
$deadline = (Get-Date).AddSeconds(90)

function Log([string]$m) {
    Add-Content -LiteralPath $log -Value ("{0:yyyy-MM-dd HH:mm:ss.fff} {1}" -f (Get-Date), $m) -Encoding UTF8
}

function EndpointReady([string]$name) {
    $d = Get-PnpDevice -Class AudioEndpoint -ErrorAction SilentlyContinue |
        Where-Object { $_.FriendlyName -eq $name -and $_.Status -eq "OK" } |
        Select-Object -First 1
    return [bool]$d
}

Log "launcher start"

$pnpReady = $false
while((Get-Date) -lt $deadline) {
    $audiosrv = Get-Service Audiosrv -ErrorAction SilentlyContinue
    $builder = Get-Service AudioEndpointBuilder -ErrorAction SilentlyContinue
    $motu = Get-PnpDevice -Class MEDIA -ErrorAction SilentlyContinue |
        Where-Object { $_.FriendlyName -eq "MOTU M Series" -and $_.Status -eq "OK" } |
        Select-Object -First 1

    if($audiosrv.Status -eq "Running" -and
       $builder.Status -eq "Running" -and
       $motu -and
       (EndpointReady "In 1-2(MOTU M Series)") -and
       (EndpointReady "CABLE Input(VB-Audio Virtual Cable)")) {
        $pnpReady = $true
        Log "PnP/audio services ready"
        break
    }
    Start-Sleep -Seconds 1
}

if(-not $pnpReady) {
    Log "PnP/audio services timeout; Light Host not started"
    exit 2
}

# Remove any early/stale instance before testing the real streams.
Get-Process -Name "Light Host" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 300

# Actually open/start the exact 48 kHz input and output streams Light Host needs.
# Retry only as long as needed; there is no fixed post-boot delay.
$probe = @"
import sounddevice as sd
import time

wanted_in = "In 1-2(MOTU M Series)"
wanted_out = "CABLE Input(VB-Audio Virtual Cable)"
devs = sd.query_devices()
apis = [sd.query_hostapis(i)["name"] for i in range(len(sd.query_hostapis()))]

iin = iout = None
for i, d in enumerate(devs):
    api = apis[d["hostapi"]]
    if api == "Windows WASAPI" and d["name"] == wanted_in and d["max_input_channels"] >= 2:
        iin = i
    if api == "Windows WASAPI" and d["name"] == wanted_out and d["max_output_channels"] >= 2:
        iout = i

if iin is None or iout is None:
    raise SystemExit(2)

inp = out = None
try:
    inp = sd.InputStream(device=iin, channels=2, samplerate=48000, dtype="float32")
    out = sd.OutputStream(device=iout, channels=2, samplerate=48000, dtype="float32")
    inp.start()
    out.start()
    time.sleep(0.15)
    if not inp.active or not out.active:
        raise RuntimeError("stream did not become active")
    print("READY48_ACTIVE")
finally:
    if out is not None:
        try:
            out.stop()
        except Exception:
            pass
        try:
            out.close()
        except Exception:
            pass
    if inp is not None:
        try:
            inp.stop()
        except Exception:
            pass
        try:
            inp.close()
        except Exception:
            pass
"@

$ready48 = $false
for($i=0; $i -lt 120; $i++) {
    $out = $probe | py -3 - 2>$null
    if($LASTEXITCODE -eq 0 -and $out -match "READY48_ACTIVE") {
        $ready48 = $true
        break
    }
    Start-Sleep -Milliseconds 750
}
Log ("48k active probe=" + $ready48)

if(-not $ready48) {
    Log "48k active probe timeout; Light Host not started"
    exit 3
}

# Allow the successful readiness probe to release its handles, then launch immediately.
Start-Sleep -Milliseconds 300
Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -WindowStyle Minimized
Log "Light Host started"