========================================
EQ 프로필 모음 v3 (Equalizer APO / Peace 용)
※ AF120 → AF140 정정판. 이 폴더가 최종본.
   (af120 폴더의 EQ_Profiles는 지워도 됨)

[v3 수정 내역 - 전문가 리뷰 반영]
- IER-M9: 착용 편차보다 작은 초고Q 미세필터(구 6~9번) 제거,
  핵심 6필터로 정리 (AutoEq 공식 권장 구성)
- W80: 5354Hz 필터 Q6.0/-3.0 → Q3.0/-2.0 (커플러 아티팩트 완화)
- AirPods Pro 2: 6486Hz 필터 Q5.92/-6.3 → Q3.0/-4.0 (착용 편차 대응)
- AF140: 480Hz -1.5dB 추가 (500Hz 부근 잔여 두께 제거)
- AF140 기성 프로필 부재 확인: AutoEq(oratory/crinacle/innerfidelity),
  HBB squig, 국내 CrinGraph 전부 없음. 본 프로필이 유일한 측정 기반 보정.

[v3.1 추가]
- Mobius_Flat_* 추가: 본체 Flat 프리셋용 대안 프로필 (crinacle GRAS 측정)
  → 사용 시 본체 프리셋을 Flat으로. 기본 권장은 여전히 Default + Mobius_* 조합
- IER-M9_Monitoring_Full10.txt 추가: 원본 10필터판 (6필터판과 A/B 비교용)
- W80 / AirPods Pro 2: 추가 측정 소스 부재 확인 (Rtings, Innerfidelity,
  crinacle 팁 변형판 전부 없음). 현행 crinacle 711 프로필이 유일하자 최선
- AF140 임피던스 교차 확인: Innerfidelity 실측 37옴@1kHz, 대역 내 75→18옴
  스윙 → 낮은 출력 임피던스 소스 권장 유지

[v3.2 - 이중 측정 교차검증판]
- IER-M9: oratory1990 + crinacle 두 실험실 측정의 합의 블렌드로 교체
  (두 곳에서 재현된 핵심 5필터의 중심주파수/게인 평균. 프리앰프 -6.0)
  → 두 실험실 비교 결과 큰 필터는 판박이, Q6 미세필터는 완전 상이
    = 미세필터는 개별 장비의 지문이라는 증거. Full10 파일은 비교용 보존
- AirPods Pro 2: 6486Hz 컷 -4.0 → -5.5 (Q4.0)
  (Super* Review 볼륨별 측정에서 6.5kHz 피크 실재 재확인 → 컷 복원)
  ※ 어댑티브 EQ 특성상 볼륨에 따라 응답이 변함 (Super*가 25/50/75/100%
    볼륨별로 4회 측정한 이유). 저역 보정의 신뢰도는 원래 낮음
- W80: RTINGS 리뷰 부재(404) 확인 → crinacle이 유일 정량 소스로 최종 확정

[v3.3 - W80 영디비 교차검증판]
영디비(GRAS 45CA-10 + APx500, 올리브-웰티 타겟) 측정 그래프 판독 결과 반영:
- 서브베이스 부족(20Hz -7.5dB)이 2차 확인됨 → LS 105Hz +0.6 → +2.5
- 구 5354Hz 컷 삭제: crinacle(711)은 그 자리서 피크, 영디비(45CA)는 딥으로
  상반 → 실험실 간 불일치 구간은 노터치 원칙 적용
- 중저음 험프 컷(222Hz)과 2~4k 대형 부스트는 두 실험실 일치 → 유지
- W80 임피던스 3.7옴@1kHz (영디비 실측) → 출력 임피던스 민감도 최상급.
  반드시 OI 1옴 미만 소스 사용. 프리앰프 -7.0으로 상향(클리핑 방지)
========================================

■ 설치
1. Equalizer APO 설치 (sourceforge.net/projects/equalizerapo)
   - 설치 중 Configurator 창에서 사용할 출력 장치(모비우스 USB, 3.5mm 출력 등)에 체크
   - 장치를 나중에 추가하려면: 시작 메뉴 > Configurator 재실행
2. Peace GUI 설치 (sourceforge.net/projects/peace-equalizer-apo-extension)
3. Peace 실행 → Import 버튼 → 이 폴더의 txt 파일 선택
4. 프로필별로 저장하고 단축키 지정하면 키 하나로 전환 가능

■ 파일 구성 (기기별 모니터링 / 배그용)
- Mobius_*        : Audeze Mobius   (출처: AutoEq/oratory1990, default preset 측정)
- IER-M9_*        : Sony IER-M9     (출처: AutoEq/oratory1990)
- W80_*           : Westone W80     (출처: AutoEq/crinacle 711)
- AirPodsPro2_*   : AirPods Pro 2   (출처: AutoEq/crinacle 711, ANC 모드 측정)
- AF140_*         : Audiofly AF140  (골든이어스 측정 그래프 기반 자체 제작)

■ AF140 보정 내용 (골든이어스 측정 기준)
- 100~300Hz +10dB 중저음 험프 제거 (따뜻한 맛이 사라지니, 원래 음색이
  좋으면 1번 필터를 -8 → -4로 완화)
- 3.4kHz 깊은 노치(-11.5dB)는 60~70%만 보정 (전부 메우면 링잉 발생)
- 9kHz 치찰음 피크 -5dB
- 10kHz 이상은 좌우 편차가 커서 최소로만 손댐

■ 기기별 필수 조건
- Mobius: 본체 EQ 프리셋 = Default, USB 연결, Hi-Res(2ch) 모드, 3D 끔
  (이 보정값은 Default 프리셋 기준 측정이라 Flat에 두면 어긋남)
- AirPods Pro 2: ANC 켠 상태 기준. 블루투스 지연 때문에 게임용 비추천
- W80: 3번 필터(-7.1dB)가 특유의 따뜻함을 많이 깎음. 원래 음색 좋아하면 -4로 완화
- 인이어 전부: 출력 임피던스 1옴 이하 소스 권장 (멀티드라이버라 임피던스 스윙 큼)

■ 배그(PUBG) 프로필 설명
모니터링 프로필(타깃 보정) 위에 공통 오버레이 3개 추가:
- 80Hz 로우쉘프 -4.5dB : 폭발음/차량 럼블 마스킹 제거
- 3000Hz +3.0dB (Q1.4) : 발소리/재장전 디테일
- 7500Hz +1.5dB (Q2.0) : 유리 깨짐/스냅음
인게임: 배그는 공식 스테레오 전용. 가상화(배그 HRTF, 윈도우 공간음향,
헤드셋 7.1)는 최대 1개만. 켜고 끄며 비교 후 취향대로.

■ 주의
- WASAPI 독점 모드(비트퍼펙트 재생)는 Equalizer APO를 우회함 → 공유 모드로 재생
- 보정값은 시작점. 귀에 맞게 1~2dB씩 다듬을 것
- 프리앰프 값은 클리핑 방지용이니 지우지 말 것
========================================
