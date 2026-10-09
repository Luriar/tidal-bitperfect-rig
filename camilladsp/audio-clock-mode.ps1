param(
  [Parameter(Mandatory=$true)][int]$Rate,
  [switch]$Shared
)
$ErrorActionPreference='Stop'

$valid=@(44100,48000,88200,96000,176400,192000)
if($Rate -notin $valid){ throw "Unsupported rate $Rate" }

$lightExe='C:\Program Files\Light Host 1.2.1 Win64\Light Host.exe'
$lightVbs='C:\EQ\light-host-autostart.vbs'

# Native ASIO mode must own the MOTU clock. Stop Light Host and any stale launcher.
if(-not $Shared){
  Get-Process 'Light Host' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'wscript.exe' -and $_.CommandLine -like '*light-host-autostart.vbs*'
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 300
}

$src=@"
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
public class PCClock {}
[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("F8679F50-850A-41CF-9C72-430F290290C8")]
public interface IPCClock {
 int GetMixFormat([MarshalAs(UnmanagedType.LPWStr)] string n, IntPtr p);
 int GetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string n,int d,IntPtr p);
 int ResetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string n);
 int SetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string n,IntPtr p,IntPtr m);
 int GetProcessingPeriod(string n,int d,IntPtr a,IntPtr b);
 int SetProcessingPeriod(string n,IntPtr p);
 int GetShareMode(string n,IntPtr p);
 int SetShareMode(string n,IntPtr p);
 int GetPropertyValue(string n,IntPtr k,IntPtr v);
 int SetPropertyValue(string n,IntPtr k,IntPtr v);
 int SetDefaultEndpoint(string n,int r);
 int SetEndpointVisibility(string n,int v);
}
public static class ClockFmt {
 static void W16(byte[] b,int o,ushort v){ b[o]=(byte)v; b[o+1]=(byte)(v>>8); }
 static void W32(byte[] b,int o,uint v){ b[o]=(byte)v; b[o+1]=(byte)(v>>8); b[o+2]=(byte)(v>>16); b[o+3]=(byte)(v>>24); }
 public static int Set16(string id,int rate){
   byte[] b=new byte[40];
   W16(b,0,0xFFFE); W16(b,2,2); W32(b,4,(uint)rate); W32(b,8,(uint)(rate*4));
   W16(b,12,4); W16(b,14,16); W16(b,16,22); W16(b,18,16); W32(b,20,3);
   byte[] g=new Guid("00000001-0000-0010-8000-00AA00389B71").ToByteArray();
   Array.Copy(g,0,b,24,16);
   IntPtr p=Marshal.AllocCoTaskMem(40);
   try{
     Marshal.Copy(b,0,p,40);
     var pc=(IPCClock)(new PCClock());
     return pc.SetDeviceFormat(id,p,p);
   } finally { Marshal.FreeCoTaskMem(p); }
 }
 public static int Set(string id,int rate){
   byte[] b=new byte[40];
   W16(b,0,0xFFFE); W16(b,2,2); W32(b,4,(uint)rate); W32(b,8,(uint)(rate*8));
   W16(b,12,8); W16(b,14,32); W16(b,16,22); W16(b,18,24); W32(b,20,3);
   byte[] g=new Guid("00000001-0000-0010-8000-00AA00389B71").ToByteArray();
   Array.Copy(g,0,b,24,16);
   IntPtr p=Marshal.AllocCoTaskMem(40);
   try{
     Marshal.Copy(b,0,p,40);
     var pc=(IPCClock)(new PCClock());
     return pc.SetDeviceFormat(id,p,p);
   } finally { Marshal.FreeCoTaskMem(p); }
 }
}
"@
Add-Type -TypeDefinition $src -Language CSharp

# Resolve current active MMDevice endpoint IDs dynamically.
# USB/PnP re-enumeration can leave old endpoint GUIDs behind with Status=Unknown.
function Get-ActiveAudioEndpointIds([string]$NameRegex){
  @(
    Get-PnpDevice -Class AudioEndpoint -ErrorAction SilentlyContinue |
      Where-Object { $_.Status -eq 'OK' -and $_.FriendlyName -match $NameRegex } |
      ForEach-Object { if($_.InstanceId.StartsWith('SWD\MMDEVAPI\')){$_.InstanceId.Substring(13)}else{$_.InstanceId} } |
      Sort-Object -Unique
  )
}

# Keep every currently active MOTU Windows endpoint aligned to the requested rate.
# Shared uses 48 kHz; native uses the current TIDAL track rate.
$ids=Get-ActiveAudioEndpointIds 'MOTU M Series'
if(@($ids).Count -eq 0){ throw 'No active MOTU audio endpoints found' }
$setOk=0
foreach($id in $ids){
  try{
    $hr=[ClockFmt]::Set($id,$Rate)
    if($hr -eq 0){$setOk++}else{Write-Warning "MOTU endpoint set returned HR=$hr for $id"}
  }catch{
    Write-Warning "MOTU endpoint unavailable, skipped: $id"
  }
}
if($setOk -eq 0){throw 'Failed to update every active MOTU endpoint'}

# Set the MOTU hardware selector to the same rate, ensure Sync is ON.
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class MWinClock {
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc p,IntPtr l);
 public delegate bool EnumWindowsProc(IntPtr h,IntPtr l);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);
}
"@

$mp=Get-Process MOTUMSeries -ErrorAction SilentlyContinue | Select-Object -First 1
if(-not $mp){
  Start-Process 'C:\Program Files (x86)\MOTU\CoreUAC\MOTUMSeries.exe' -WindowStyle Minimized
  Start-Sleep -Seconds 2
  $mp=Get-Process MOTUMSeries -ErrorAction Stop | Select-Object -First 1
}
$script:hw=[IntPtr]::Zero
[MWinClock]::EnumWindows({
 param($h,$l)
 [uint32]$procId=0
 [MWinClock]::GetWindowThreadProcessId($h,[ref]$procId)|Out-Null
 if($procId -eq $mp.Id){
   $sb=New-Object System.Text.StringBuilder 256
   [MWinClock]::GetWindowText($h,$sb,$sb.Capacity)|Out-Null
   if($sb.ToString() -eq 'MOTU M-Series'){ $script:hw=$h; return $false }
 }
 return $true
},[IntPtr]::Zero)|Out-Null
if($script:hw -eq [IntPtr]::Zero){ throw 'MOTU window not found' }

# MOTU UIAutomation works on its hidden main window; never show/focus the app.
[MWinClock]::ShowWindow($script:hw,0)|Out-Null
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$w=[System.Windows.Automation.AutomationElement]::FromHandle($script:hw)
function Get-El($aid){
 $c=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty,$aid)
 return $w.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$c)
}
$combo=Get-El 'sampleRateSelector'
$buffer=Get-El 'bufferSizeSelector'
$sync=Get-El 'lockWaveSR'
$low=Get-El 'useLowestLatencySafetyOffsets'
if(-not $combo -or -not $buffer -or -not $sync){ throw 'MOTU controls not found' }

# Always dismiss ComboBox popups, even if the item selection fails.
$rateMenu=$null
$bufferMenu=$null
try {
$spat=$combo.GetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern)
$cur=(($spat.Current.GetSelection())|ForEach-Object{$_.Current.Name}) -join ','
if($cur -ne [string]$Rate){
  $ep=$combo.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
  $rateMenu=$ep
  $ep.Expand(); Start-Sleep -Milliseconds 250
  $cn=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,[string]$Rate)
  $item=$combo.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$cn)
  if(-not $item){ $item=$w.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$cn) }
  if(-not $item){ throw "MOTU rate item $Rate not found" }
  $item.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
  Start-Sleep -Milliseconds 900
}
if(-not $Shared){ Write-Output "NATIVE_RATE_ALIGNED rate=$Rate previous=$cur" }
# Buffer 2048
$bsp=$buffer.GetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern)
$bcur=(($bsp.Current.GetSelection())|ForEach-Object{$_.Current.Name}) -join ','
if($bcur -ne '2048'){
  $bep=$buffer.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
  $bufferMenu=$bep
  $bep.Expand(); Start-Sleep -Milliseconds 200
  $bn=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'2048')
  $bi=$buffer.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$bn)
  if(-not $bi){ $bi=$w.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$bn) }
  if($bi){ $bi.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select(); Start-Sleep -Milliseconds 500 }
}
$tp=$sync.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
if($tp.Current.ToggleState.ToString() -eq 'Off'){ $tp.Toggle(); Start-Sleep -Milliseconds 300 }
if($low){
  $ltp=$low.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
  if($ltp.Current.ToggleState.ToString() -eq 'On'){ $ltp.Toggle(); Start-Sleep -Milliseconds 300 }
}
 } finally {
  foreach($menu in @($bufferMenu,$rateMenu)) {
    if($null -ne $menu){ try { $menu.Collapse() } catch { } }
  }
  # Keep both MOTU window and its drop-downs out of the desktop.
  [MWinClock]::ShowWindow($script:hw,0)|Out-Null
}

  # Keep current VAC Line 1 render/capture endpoints aligned to the requested rate.
  $vacIds=Get-ActiveAudioEndpointIds '^Line 1\(Virtual Audio Cable\)$'
  foreach($vac in $vacIds){
    try{
      $hr=[ClockFmt]::Set($vac,$Rate)
      if($hr -ne 0){Write-Warning "VAC rate set returned HR=$hr for $vac"}
    }catch{
      Write-Warning "VAC shared endpoint unavailable, skipped: $vac"
    }
  }


if($Shared){
  # Light Host output endpoint is fixed 48 kHz / 16-bit.
  $vbIds=Get-ActiveAudioEndpointIds '^CABLE Input\(VB-Audio Virtual Cable\)$'
  if(@($vbIds).Count -eq 0){
    Write-Warning 'Active CABLE Input endpoint not found'
  }else{
    foreach($vbRender in $vbIds){
      try{
        $hr=[ClockFmt]::Set16($vbRender,48000)
        if($hr -ne 0){Write-Warning "VB-Cable 48k set returned HR=$hr for $vbRender"}
      }catch{
        Write-Warning "VB-Cable endpoint unavailable, skipped: $vbRender"
      }
    }
  }

  # Clear stale launchers, then use the known 48k launcher. Direct-start fallback keeps mic alive if probe UI hangs.
  Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'wscript.exe' -and $_.CommandLine -like '*light-host-autostart.vbs*'
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  if(-not (Get-Process 'Light Host' -ErrorAction SilentlyContinue)){
    Start-Process -FilePath 'wscript.exe' -ArgumentList ('"'+$lightVbs+'"')
    $deadline=(Get-Date).AddSeconds(10)
    while((Get-Date) -lt $deadline -and -not (Get-Process 'Light Host' -ErrorAction SilentlyContinue)){
      Start-Sleep -Milliseconds 500
    }
  }
  if(-not (Get-Process 'Light Host' -ErrorAction SilentlyContinue) -and (Test-Path $lightExe)){
    Get-CimInstance Win32_Process | Where-Object {
      $_.Name -eq 'wscript.exe' -and $_.CommandLine -like '*light-host-autostart.vbs*'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Process -FilePath $lightExe -WindowStyle Minimized
    Start-Sleep -Seconds 2
  }
}

$mode=if($Shared){'shared'}else{'native'}
"$(Get-Date -Format o) mode=$mode rate=$Rate lightHost=$([bool](Get-Process 'Light Host' -ErrorAction SilentlyContinue))" |
  Add-Content -Encoding UTF8 'C:\CamillaDSP\audio-clock-mode.log'
Write-Output "CLOCK_MODE_OK mode=$mode rate=$Rate"
