# TIDAL Bit-Perfect Rig

Windows에서 **TIDAL 독점 재생 + 곡별 native sample rate + CamillaDSP EQ + shared 48 kHz 복귀**를 자동화한 개인 오디오 구성입니다.  
현재 기준 안정 상태는 **2026-10-07**이며, 기본 청취 프로파일은 **Westone W80**입니다.

## 현재 안정 상태

- TIDAL 재생 시: `TIDAL Exclusive -> Line 1 (Virtual Audio Cable) -> CamillaDSP WASAPI exclusive capture -> MOTU M Series ASIO`
- CamillaDSP/MOTU가 소스 레이트를 직접 따라감: 44.1 / 48 / 88.2 / 96 / 176.4 / 192 kHz
- 곡 레이트 변경 시 **TIDAL Pause/Play 명령 없이 hot switch**
- 같은 곡 seek 시 **seek de-click v2**가 TIDAL의 WASAPI 재오픈 구간을 mute로 가려 클릭을 억제
- CamillaDSP: `chunksize: 256`, `volume_ramp_time: 2.0`
- W80 native preamp: `-10.5 dB`
- TIDAL 정지/유휴 시 CamillaDSP가 MOTU를 반납하고 shared 48 kHz로 복귀
- shared 상태에서는 Light Host가 자동 기동되어 기존 MOTU input -> VB-CABLE 체인을 복구
- 부팅/로그온 자동 시작: CamillaDSP supervisor + Light Host launcher

세부 변경 이력은 [`CHANGELOG.md`](CHANGELOG.md)를 참고하세요.

## W80 기본값

현재 **W80이 양쪽 모두 기본**입니다.

- Native/TIDAL: `camilladsp/config_template.yml` = W80, preamp `-10.5 dB`
- 수동 W80 스위치: `camilladsp/music_w80.yml`도 위 안정 템플릿과 동일
- Shared/게임/일상 M4 EqAPO: `eq/current_m4.txt -> W80_Monitoring.txt`

`MUSIC_EQ_M9.bat`, `MUSIC_EQ_AF140.bat` 등을 직접 실행할 때만 해당 프로파일로 바뀝니다.

## 구조

```text
[TIDAL 재생]
TIDAL (Exclusive, source native rate)
  -> Virtual Audio Cable: Line 1
  -> CamillaDSP (WASAPI exclusive capture)
  -> MOTU M Series ASIO (same native rate)

[곡 sample-rate 변경]
TIDAL metadata + VAC live rate
  -> 일치 시 hot switch
  -> TIDAL transport는 건드리지 않음

[같은 곡 seek]
media.seek 감지
  -> Camilla mute
  -> TIDAL 새 WASAPI render thread 확인
  -> 60 ms settle
  -> unmute

[TIDAL 정지/유휴]
CamillaDSP stop
  -> shared 48 kHz 복귀
  -> Light Host 자동 기동
```

## 저장소 구성

| 경로 | 복구 위치 | 역할 |
|---|---|---|
| `camilladsp/` | `C:\CamillaDSP` | supervisor, native clock, W80/M9/AF140 템플릿, 제어 스크립트 |
| `eq/` | `C:\EQ` | Equalizer APO 프로파일/스위치 |
| `light-host/` | `%APPDATA%\Light Host` + `C:\EQ` | 현재 Light Host settings snapshot + 자동기동 스크립트 |
| `restore_this_pc.ps1` | 저장소 루트에서 실행 | 포맷 후 현재 사용자 설정 복구 |

## 포맷 후 복구

### 중요한 한계

**Git clone 하나만으로 드라이버/상용 프로그램까지 복원되지는 않습니다.** 다음 서드파티 구성요소는 별도 설치가 필요합니다.

- MOTU M Series 드라이버
- Virtual Audio Cable 정식판 (Muzychenko VAC)
- VB-Audio Virtual Cable (Light Host 출력 `CABLE Input`용)
- TIDAL Desktop
- Python 3.12 (`py` launcher 포함)
- CamillaDSP v4.x Windows ASIO 빌드의 `camilladsp.exe`
- Equalizer APO
- Light Host 1.2.1 Win64
- 현재 Light Host 플러그인 체인을 그대로 쓰려면 동일한 VST/VST3 플러그인도 재설치
  - 저장소에는 **설정만** 보관하며 플러그인 바이너리/라이선스는 포함하지 않음

### 가장 빠른 복구 순서

1. 위 필수 프로그램/드라이버를 설치합니다.
2. CamillaDSP ASIO 실행파일을 `C:\CamillaDSP\camilladsp.exe`에 둡니다.
3. 이 저장소를 clone 합니다.
4. **관리자 PowerShell**에서 저장소 루트로 이동해 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\restore_this_pc.ps1
```

이 스크립트가 자동으로 수행하는 작업:

- repo `camilladsp/` -> `C:\CamillaDSP` 복구
- repo `eq/` -> `C:\EQ` 복구
- W80을 native/shared 기본으로 재설정
- Python 의존성 `sounddevice numpy websocket-client winsdk` 설치/복구
- Light Host settings snapshot을 `%APPDATA%\Light Host`로 복구
- Camilla supervisor 로그온 자동시작 등록
- Light Host 로그온 자동시작 등록
- Equalizer APO `config.txt`를 `C:\EQ\eqapo_master.txt`에 연결
- supervisor Python 문법 검사
- 설치된 필수 구성요소 상태 확인
- 필수 구성요소가 모두 있으면 현재 세션에서 launcher 시작

### 포맷 후 수동으로 한 번 확인해야 하는 항목

자동화하기 어렵거나 장치 설치 순서에 따라 달라지는 항목입니다.

1. **TIDAL**
   - 출력: `Line 1 (Virtual Audio Cable)`
   - Exclusive mode: ON
   - 변경 후 TIDAL 완전 종료/재실행

2. **VAC**
   - SR range: `22050..192000`
   - BPS: `8..32`
   - NC: `1..2`
   - Stream format limit: Cable range
   - Volume control: OFF
   - Channel mixing: OFF

3. **Equalizer APO Configurator**
   - 실제 청취 endpoint만 적용
   - `Line 1` / `CABLE` 계열에는 적용하지 않음

4. **Light Host 플러그인**
   - 저장된 `Light Host.settings`는 현재 device routing과 plugin state를 복원
   - 같은 플러그인 파일이 설치되어 있어야 완전 동일하게 재현됨

## 기존 설치에서 자동시작만 다시 등록

`C:\CamillaDSP\install_autostart.bat`를 실행하면 Camilla supervisor와 Light Host launcher를 둘 다 Startup에 등록합니다.  
재부팅은 스크립트가 수행하지 않습니다.

## 현재 핵심 파일

- `camilladsp/supervisor.py`
  - TIDAL/VAC rate 판정
  - native hot switch
  - seek de-click v2
  - native/shared 상태 전환
- `camilladsp/audio-clock-mode.ps1`
  - Windows endpoint / MOTU clock / Light Host coordination
- `camilladsp/config_template.yml`
  - 기본 W80 native profile
- `camilladsp/music_w80.yml`
  - 수동 W80 전환 시에도 안정값 유지
- `light-host/Light Host.settings`
  - 현재 Light Host routing/plugin state snapshot

## 검증된 현재 값

```text
W80 preamp         -10.5 dB
Camilla chunksize  256
Mute ramp          2.0 ms
Shared baseline    48 kHz
Native output      MOTU M Series ASIO
Capture            Line 1 (Virtual Audio Cable), WASAPI exclusive
```

2026-10-07 실제 테스트에서 44.1 kHz native 재생과 반복 seek de-click 동작을 확인했고, seek 구간의 TIDAL `buffer_underruns`는 0이었습니다.
