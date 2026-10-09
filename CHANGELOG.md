# Changelog

## 2026-10-09 ? Hidden MOTU sample-rate controls

- TIDAL/native-to-shared rate changes no longer call `ShowWindow(..., 4)` on the MOTU control panel.
- Audio clock script keeps the MOTU window hidden while using UI Automation.
- Always collapses rate/buffer dropdowns in `finally`, including on failure, to prevent orphan popups / desktop ghosting.
- Unchanged-rate transitions skip expanding the sample-rate dropdown entirely.
- No change to W80, CamillaDSP buffers, native rates or the shared 48 kHz design.
- Static PowerShell parse and live/repo file hash checks passed; real TIDAL cross-rate playback still needs confirmation.

## 2026-10-07 — Native/seek 안정화

- TIDAL 재생 중 소스 샘플레이트를 MOTU ASIO가 직접 소유하도록 native clock 전환 로직 정리.
- 샘플레이트 변경 시 TIDAL `Pause/Play`를 건드리지 않는 hot switch로 변경.
- TIDAL metadata와 VAC live rate가 일치하면 즉시 전환하고, 불일치/seek transient는 보류.
- 같은 곡 seek 시 TIDAL WASAPI teardown/reopen에서 발생하던 클릭을 `seek de-click v2`로 마스킹.
  - seek 감지 즉시 Camilla mute
  - 새 WASAPI render thread 확인
  - 60 ms settle 후 unmute
- CamillaDSP `chunksize`를 실제 벤치 결과에 따라 `256`으로 확정.
- `volume_ramp_time: 2.0` 적용.
- W80 기본 preamp를 `-10.5 dB`로 확정.
- `music_w80.yml`을 현재 안정 `config_template.yml`과 동기화해 W80 스위치 시 구설정으로 회귀하지 않도록 수정.
- native 종료/유휴 시 shared 48 kHz 복귀 및 Light Host 자동실행 구조 유지.
- 현재 Light Host autostart 및 settings snapshot을 저장소에 포함.
- `restore_this_pc.ps1` 추가: 포맷 후 서드파티 필수 프로그램 설치 뒤 현재 사용자 설정을 한 번에 복구.

### 현재 검증 기준

- native 44.1 kHz 실제 재생 확인.
- 반복 seek에서 `mute -> new WASAPI render -> settle -> unmute` 정상 반복.
- TIDAL `buffer_underruns: 0` 확인.
- CamillaDSP startup 시 초기 ASIO underrun 외 seek 중 추가 underrun 없음.
- W80: native CamillaDSP와 shared M4 EqAPO 모두 기본 프로파일.
