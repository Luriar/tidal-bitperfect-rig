# TIDAL Bit-Perfect Rig

TIDAL 독점 모드의 **비트퍼펙트 재생**과 **DSP(EQ·룸보정 자리)**를 동시에 성립시키고
곡의 샘플레이트(44.1~192kHz)를 **자동 추종**하는 Windows 오디오 시스템.
전부 무료 소프트웨어 + VAC 라이선스 1개로 구성. (2026-08 제작·실사용 검증)

```
[음감]   TIDAL(독점, 곡 네이티브 레이트)
           → Virtual Audio Cable "Line 1" (레이트 일치 = 무변환 통과)
           → CamillaDSP (WASAPI 독점 캡처 → 무필터 or 헤드폰 EQ)
           → 출력 A: MOTU M4 ASIO (스피커/이어폰, 무리샘플)
             출력 B: Audeze Mobius WASAPI 독점 (96k 고정, Accurate 리샘플)
         ※ supervisor.py가 곡 레이트를 감지해 체인을 자동 재조립 (전환 ~2.5초)

[게임/일상]  음악 정지 60초 후 DAC 자동 반납 → 공유 모드 + EqAPO 프로파일

[마이크]  실마이크 → 보이스체인저 → VB-CABLE (이 시스템과 완전 분리, 불간섭)
```

## 폴더

| 폴더 | 설치 위치 | 내용 |
|---|---|---|
| `camilladsp/` | `C:\CamillaDSP\` | 수퍼바이저(자동화 전부), 음감 모드 템플릿·스위치, 운영 bat |
| `eq/` | `C:\EQ\` | EqAPO 프로파일 15종 + 전환 스위치 18종 (게임/공유 경로용) |

상세 아키텍처·동작 원리·**트러블슈팅 사전**(하룻밤의 모든 삽질과 해법)은
`camilladsp/README_빌드가이드.txt` 참조. EQ 스위치 사용법은 `eq/스위치_사용법.txt`.

---

## 제로부터 재현 (새 컴퓨터 / 초기화 후)

### 준비물
- Windows 10/11, TIDAL 데스크톱 앱
- **Virtual Audio Cable 4.7x** (뮤지첸코): https://vac.muzychenko.net 에서 **라이선스 구매** 후 정식판 설치
  (트라이얼은 주기적 음성 워터마크. 크랙판은 커널 드라이버라 보안 위험이 큼. 구매 권장)
- **CamillaDSP v4.x ASIO 빌드**: GitHub HEnquist/camilladsp 릴리스의 `camilladsp-windows-asio-amd64.zip`
- **Python 3.12** (설치 시 py 런처 포함)
- **Equalizer APO 1.4.x** (SourceForge)
- 이 저장소

### 설치 순서

1. **Python** 설치 후:
   ```
   py -3 -m pip install sounddevice numpy websocket-client winsdk
   ```

2. **VAC 설치** → 재부팅 → VAC Control Panel에서 케이블 1개, 다음으로 설정 후 Set:
   - SR range `22050..192000`, BPS `8..32`, NC `1..2`
   - Stream fmt limit = `Cable range`
   - `Volume control` **끔**, `Channel mixing` **끔** (투명성)
   - ※ 케이블 설정 변경은 Streams=0일 때만 가능 (TIDAL이 물고 있으면 출력장치 잠깐 변경)

3. **CamillaDSP**: zip을 `C:\CamillaDSP\`에 풀고(→ `C:\CamillaDSP\camilladsp.exe`),
   이 저장소의 `camilladsp/` 내용물을 같은 폴더에 복사.

4. **EQ**: 저장소의 `eq/` 내용물을 `C:\EQ\`로 복사.

5. **오디오 장치 드라이버** (예: MOTU M Series) 설치. MOTU 기준 패널 설정:
   버퍼 512 이상, "Use lowest latency safety offsets" 끔.

6. **TIDAL**: 설정 → 사운드 출력 = `Line 1 (Virtual Audio Cable)` + **독점 모드 켬**.
   ⚠️ 독점 토글은 "다음 스트림부터" 적용. 변경 후 TIDAL을 **트레이까지 완전 종료** 후 재실행.

7. **윈도우 소리 설정** (제어판 → 소리):
   - 재생 기본 장치 = 메인 DAC 출력 (예: `Out 1-2 (MOTU M Series)`). Line 1로 두면 안 됨
   - 녹음 기본 장치 = 마이크 체인 출구 (Line 1로 두면 음악이 보이스챗에 송출되는 사고 발생!)
   - 통신 탭 = "아무 작업도 하지 않음" (통화 시 음악 자동 감쇠 방지)

8. **장치명 확인**: `C:\CamillaDSP\run_list.bat` 실행 → `devices_console.txt`에서
   케이블 캡처명과 출력장치명을 확인해 `supervisor.py` 상단 상수에 반영:
   ```python
   CAPTURE_DEVICES  = ["Line 1(Virtual Audio Cable)"]   # 공백 유무 주의! 실측값 사용
   PLAYBACK_DEVICES = ["MOTU M Series"]                  # ASIO 드라이버명
   ```
   모비우스 모드를 쓰면 `music_mobius.yml`의 playback device 명도 실측값으로.

9. **첫 가동**: `run_supervisor.bat` 더블클릭 → TIDAL 재생 →
   콘솔/`supervisor.log`에 `재생 감지 → 성공: NNNNHz / S24`가 뜨면 성공.
   레이트 다른 곡으로 넘겨 `레이트 전환 감지 → 성공(전환) → TIDAL 재개` 확인.
   ⚠️ 콘솔 창에서 텍스트를 드래그하면 프로세스가 얼어붙음(quick-edit). 선택하지 말 것.

10. **부팅 자동 시작**: `install_autostart.bat` 더블클릭 (이후 부팅부터 완전 백그라운드).

11. **EqAPO**: 설치 → Configurator에서 **실제 청취 장치만** 체크
    (예: Out 1-2, 모비우스, 에어팟 스테레오. **Line 1·CABLE 계열은 절대 체크 금지**) → 재부팅
    → `C:\EQ`의 아무 스위치 bat 하나 실행하면 배선 완료 (관리자 불필요).

12. **검증**: 유튜브 틀고 `EQ_M4_TEST.bat`(볼륨 -25dB) ↔ 복구 스위치로 EqAPO 생존 확인.
    음감 체인은 `validate_template.bat`로 템플릿 문법 사전 검사 가능.

### 일상 사용

| 하고 싶은 것 | 실행 (더블클릭) |
|---|---|
| 스피커로 음감 (무보정) | `C:\CamillaDSP\MUSIC_EQ_OFF.bat` |
| W80 / M9 / AF140 꽂고 음감 | `MUSIC_EQ_W80 / _M9 / _AF140.bat` |
| 모비우스 헤드폰으로 음감 | `MUSIC_MOBIUS.bat` (하이레즈 2ch 모드 + HQ 프리셋 Default) |
| 게임·유튜브 쪽 EQ 전환 | `C:\EQ\EQ_M4_*.bat`, `EQ_MOBIUS_*.bat`, `EQ_AIRPODS_*.bat` |
| 시스템 정지 / TIDAL 제어 | `stop_all.bat` / `zz_pause.bat`·`zz_play.bat` |

음감용 스위치는 체인을 2초 재조립 후 적용. EqAPO 스위치는 즉시 적용.
모든 bat은 위치 독립(%~dp0)이라 폴더를 옮겨도 동작 (자동시작 vbs 경로만 갱신).

### 다른 장비에 맞추기
- 다른 DAC: `PLAYBACK_DEVICES`(ASIO명) 또는 템플릿의 Wasapi device명만 교체
- 다른 헤드폰: EqAPO 형식 프로파일 txt를 `eq/`에 넣고 스위치 bat 한 줄 복제,
  음감 체인용은 `music_*.yml`의 filters 블록에 같은 파라미터를 Biquad로 변환
  (변환 규칙: `Preamp→Gain`, `PK→Peaking`, `LSC→Lowshelf`, `HSC→Highshelf`)

## 크레딧
- 측정 데이터: oratory1990, crinacle, 골든이어스(GoldenEars). EQ 프로파일은 이들 측정 기반 자작
- [CamillaDSP](https://github.com/HEnquist/camilladsp) (HEnquist), [Equalizer APO](https://sourceforge.net/projects/equalizerapo/),
  [Virtual Audio Cable](https://vac.muzychenko.net) (E. Muzychenko · 유료, 라이선스 구매 필요)
- 설계·구현: 에이치 + Claude, 2026-08-26~27의 아주 긴 밤
