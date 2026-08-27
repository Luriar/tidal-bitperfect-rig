# -*- coding: utf-8 -*-
"""
CamillaDSP 수퍼바이저 v0.2 (루트 A)
  - 케이블 신호 감지 → 레이트/포맷/장치명 프로브 → CamillaDSP 기동 (M4 독점)
  - 무음 지속 → 종료 (M4 반납 → EqAPO/공유 복귀)
  - 스트림 깨짐(레이트 전환) → 즉시 재프로브
  - v0.2: 카밀라 에러 로그 수집, 장치명 후보 자동 시도, 빠른 실패 판정
사용법:  py -3 supervisor.py --list   /   py -3 supervisor.py
"""

import json
import os
import subprocess
import sys
import time

import numpy as np
import sounddevice as sd

# ========== 사용자 설정 ==========
CAMILLA_EXE = r"C:\CamillaDSP\camilladsp.exe"
CAPTURE_DEVICES = [
    "Line 1(Virtual Audio Cable)",     # 실측명 (풀버전에서도 no-space 확인, 21:13 로그)
]
PLAYBACK_DEVICES = [
    "MOTU M Series",              # ASIO 드라이버 실측명 (에러 로그의 Available devices 확인)
]
RATES = [44100, 96000, 48000, 192000, 88200, 176400]   # VAC 실험: 레이트 추종 부활
CAPTURE_FORMATS = ["S24", "S32", "S16"]
PLAYBACK_FORMAT = "S24"
WS_PORT = 1234
RMS_START_DBFS = -60.0
SILENCE_STOP_SEC = 60   # 무음 1분 후 M4 반납 (게임/일상 복귀)
POLL_IDLE_SEC = 1.0
# =================================

LAST_GOOD = {"fmt": None, "capdev": None, "pbdev": None}

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(HERE, "config_template.yml")
ACTIVE_PATH = os.path.join(HERE, "config_active.yml")
LOG_PATH = os.path.join(HERE, "supervisor.log")
CAMILLA_LOG = os.path.join(HERE, "camilla_last.log")


def log(msg):
    line = time.strftime("[%H:%M:%S] ") + str(msg)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def list_devices():
    txt = str(sd.query_devices())
    with open(os.path.join(HERE, "devices_list.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    try:
        print(txt)
    except UnicodeEncodeError:
        print("(devices_list.txt 참조)")


def find_capture_index():
    for i, d in enumerate(sd.query_devices()):
        if "line 1" in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    return None


def cable_rms_dbfs(dev_index, seconds=0.15):
    try:
        rec = sd.rec(int(seconds * 44100), samplerate=44100, channels=2,
                     device=dev_index, dtype="float32")
        sd.wait()
        rms = float(np.sqrt(np.mean(rec ** 2)))
        return -120.0 if rms <= 0 else 20.0 * np.log10(rms)
    except Exception:
        return None


def render_config(rate, cap_fmt, cap_dev, pb_dev):
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        cfg = f.read()
    # 모비우스 모드용 조건 렌더: ≤96k는 네이티브 그대로, >96k만 96k로 정밀 리샘플
    m_rate = min(rate, 96000)
    if rate > 96000:
        m_res = ("  capture_samplerate: {}\n"
                 "  enable_rate_adjust: true\n"
                 "  resampler:\n"
                 "    type: AsyncSinc\n"
                 "    profile: Accurate\n").format(rate)
    else:
        m_res = ""
    cfg = (cfg.replace("{{RATE}}", str(rate))
              .replace("{{MOBIUS_RATE}}", str(m_rate))
              .replace("{{MOBIUS_RESAMPLE}}\n", m_res)
              .replace("{{CAPTURE_DEVICE}}", cap_dev)
              .replace("{{PLAYBACK_DEVICE}}", pb_dev)
              .replace("{{CAPTURE_FORMAT}}", cap_fmt)
              .replace("{{PLAYBACK_FORMAT}}", PLAYBACK_FORMAT))
    with open(ACTIVE_PATH, "w", encoding="utf-8") as f:
        f.write(cfg)


VAC_LOG = os.path.join(HERE, "vaclog.log")


def vac_save_log_click():
    """VAC 제어판의 'Save log' → 파일 대화상자에 VAC_LOG 경로 저장 (컴퓨터 제어 아님, Win32).
    수퍼바이저와 같은(관리자) 권한이면 버튼/대화상자 조작 가능."""
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        mains = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def et(h, _):
            b = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(h, b, 256)
            if b.value.startswith("Virtual Audio Cable Control Panel"):
                mains.append(h)
            return True
        u32.EnumWindows(et, 0)
        if not mains:
            return False
        # Save log 버튼 찾기
        btn = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def eb(h, _):
            c = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(h, c, 64)
            if c.value == "Button":
                b = ctypes.create_unicode_buffer(64)
                u32.GetWindowTextW(h, b, 64)
                if "Save log" in b.value:
                    btn.append(h)
            return True
        u32.EnumChildWindows(mains[0], eb, 0)
        if not btn:
            return False
        u32.SendMessageW(btn[0], 0x00F5, 0, 0)  # BM_CLICK → 저장 대화상자 오픈
        time.sleep(0.6)
        # "Save"/"저장" 대화상자에 경로 입력
        dlgs = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def ed(h, _):
            b = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(h, b, 256)
            if ("save" in b.value.lower() or "저장" in b.value or
                    "event log" in b.value.lower()):
                dlgs.append(h)
            return True
        u32.EnumWindows(ed, 0)
        for dlg in dlgs:
            edits = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def ee(h, _):
                c = ctypes.create_unicode_buffer(64)
                u32.GetClassNameW(h, c, 64)
                if c.value == "Edit":
                    edits.append(h)
                return True
            u32.EnumChildWindows(dlg, ee, 0)
            if edits:
                if os.path.exists(VAC_LOG):
                    try:
                        os.remove(VAC_LOG)
                    except OSError:
                        pass
                u32.SendMessageW(edits[0], 0x000C, 0, VAC_LOG)  # WM_SETTEXT
                time.sleep(0.15)
                u32.PostMessageW(dlg, 0x0111, 1, 0)  # WM_COMMAND IDOK
                time.sleep(0.4)
                return os.path.exists(VAC_LOG)
        return False
    except Exception:
        return False


TIDAL_LOG = os.path.expandvars(r"%APPDATA%\TIDAL\Logs\player.log")


_ORACLE_RE = None


def vac_current_rate():
    """[v1.1 오라클] TIDAL player.log 증분 tail — 새로 추가된 부분만 읽어 초저비용 폴링.
    디코더 라인(트랙 로드 시 기록)에서 소스 레이트 추출, 마지막 값 유지."""
    global _ORACLE_RE
    import re as _re
    if _ORACLE_RE is None:
        _ORACLE_RE = _re.compile(
            r"Decoder got\s+\d+\s+total frames for\s+AudioMetadata\s*\[\s*"
            r"channels:\s*\d+\s+bitsPerSample:\s*\d+\s+sampleRate:\s*(\d{4,6})")
    try:
        sz = os.path.getsize(TIDAL_LOG)
        pos = LAST_GOOD.get("tlog_pos")
        if pos is None or sz < pos:          # 최초 or 로그 로테이션
            pos = max(0, sz - 524288)
        if sz > pos:
            with open(TIDAL_LOG, "rb") as f:
                f.seek(pos)
                data = f.read(sz - pos).decode("utf-8", "replace")
            LAST_GOOD["tlog_pos"] = sz
            for m in _ORACLE_RE.finditer(data):
                r = int(m.group(1))
                if r in RATES:
                    LAST_GOOD["tlog_rate"] = r
        return LAST_GOOD.get("tlog_rate")
    except OSError:
        return LAST_GOOD.get("tlog_rate")


_LV_LVITEM = None


def _lv_init():
    """VAC 제어판 리스트뷰 핸들/원격 버퍼 캐시 구성 (즉답 오라클)"""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                 wintypes.WPARAM, wintypes.LPARAM]
    u32.SendMessageW.restype = ctypes.c_ssize_t
    k32.VirtualAllocEx.restype = ctypes.c_void_p
    k32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                   ctypes.c_size_t, wintypes.DWORD,
                                   wintypes.DWORD]
    k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_size_t)]
    k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_size_t,
                                      ctypes.POINTER(ctypes.c_size_t)]
    mains, lvs = [], []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def et(h, _):
        b = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(h, b, 256)
        if b.value.startswith("Virtual Audio Cable Control Panel"):
            mains.append(h)
        return True
    u32.EnumWindows(et, 0)
    if not mains:
        # 패널이 닫혀 있으면 최소화로 자동 실행 (60초 쿨다운, 다음 폴링에서 부착)
        now = time.time()
        if now - LAST_GOOD.get("lv_spawn_t", 0) > 60:
            LAST_GOOD["lv_spawn_t"] = now
            exe = r"C:\Program Files\Virtual Audio Cable\vcctlpan.exe"
            if os.path.exists(exe):
                try:
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0  # SW_HIDE 요청 (vcctlpan이 무시할 수 있음)
                    subprocess.Popen([exe], startupinfo=si)
                    LAST_GOOD["lv_hide"] = True  # 다음 부착 때 창을 직접 숨김
                    log("VAC 제어판 자동 실행 (숨김, 즉답 오라클용)")
                except OSError:
                    pass
        LAST_GOOD["lv"] = None
        return

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def ec(h, _):
        c = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, c, 64)
        if c.value == "SysListView32":
            lvs.append(h)
        return True
    u32.EnumChildWindows(mains[0], ec, 0)
    if not lvs:
        LAST_GOOD["lv"] = None
        return
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(lvs[0], ctypes.byref(pid))
    hp = k32.OpenProcess(0x38, False, pid.value)
    if not hp:
        LAST_GOOD["lv"] = None
        return
    rtext = k32.VirtualAllocEx(hp, None, 1024, 0x3000, 4)
    rlvi = k32.VirtualAllocEx(hp, None, 256, 0x3000, 4)
    if not rtext or not rlvi:
        k32.CloseHandle(hp)
        LAST_GOOD["lv"] = None
        return
    LAST_GOOD["lv"] = (lvs[0], hp, rtext, rlvi)
    LAST_GOOD["lv_main"] = mains[0]
    # 우리가 띄운 창은 '리스트뷰가 채워진 뒤에' 숨긴다 (vac_lv_info 성공 시).
    # 빈 채로 즉시 숨기면 영영 빈 값으로 얼어붙는 것 실측됨 (03:50 사고)


def _lv_cell(sub):
    """케이블 행(0)의 sub 열 텍스트 (LVM_GETITEMTEXTW, 원격 메모리)"""
    import ctypes
    global _LV_LVITEM
    if _LV_LVITEM is None:
        class LVITEM(ctypes.Structure):
            _fields_ = [("mask", ctypes.c_uint), ("iItem", ctypes.c_int),
                        ("iSubItem", ctypes.c_int), ("state", ctypes.c_uint),
                        ("stateMask", ctypes.c_uint),
                        ("pszText", ctypes.c_void_p),
                        ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int),
                        ("lParam", ctypes.c_ssize_t),
                        ("iIndent", ctypes.c_int), ("iGroupId", ctypes.c_int),
                        ("cColumns", ctypes.c_uint),
                        ("puColumns", ctypes.c_void_p),
                        ("piColFmt", ctypes.c_void_p),
                        ("iGroup", ctypes.c_int)]
        _LV_LVITEM = LVITEM
    lv, hp, rtext, rlvi = LAST_GOOD["lv"]
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    lvi = _LV_LVITEM()
    lvi.iSubItem = sub
    lvi.pszText = rtext
    lvi.cchTextMax = 500
    wrote = ctypes.c_size_t()
    k32.WriteProcessMemory(hp, ctypes.c_void_p(rlvi), ctypes.byref(lvi),
                           ctypes.sizeof(lvi), ctypes.byref(wrote))
    u32.SendMessageW(lv, 0x1073, 0, rlvi)
    b = ctypes.create_unicode_buffer(512)
    k32.ReadProcessMemory(hp, ctypes.c_void_p(rtext), b, 1000,
                          ctypes.byref(wrote))
    return b.value


def vac_lv_info():
    """[즉답 오라클] 케이블 행 실측: (현재 포맷 레이트, 렌더 스트림 수).
    sub9='ExtPCM/48000/16/2', sub11=Pb stms (2026-08-26 실측).
    TIDAL 로그 플러시 지연과 무관. 패널 부재 시 (None, None)"""
    import re as _re
    try:
        import ctypes
        if not LAST_GOOD.get("lv") or \
                not ctypes.windll.user32.IsWindow(LAST_GOOD["lv"][0]):
            _lv_init()
        if not LAST_GOOD.get("lv"):
            return (None, None)
        m = _re.search(r"/(\d{4,6})/", _lv_cell(9) or "")
        rate = int(m.group(1)) if m else None
        if rate not in RATES:
            rate = None
        pb = (_lv_cell(11) or "").strip()
        # 데이터가 실제로 읽힌 뒤에만 (우리가 띄운) 창을 숨김
        if (m or pb.isdigit()) and LAST_GOOD.get("lv_hide"):
            LAST_GOOD.pop("lv_hide", None)
            try:
                ctypes.windll.user32.ShowWindow(LAST_GOOD.get("lv_main"), 0)
                log("VAC 제어판 창 숨김 처리 완료 (데이터 확인 후)")
            except Exception:
                pass
        return (rate, int(pb) if pb.isdigit() else None)
    except Exception:
        LAST_GOOD["lv"] = None
        return (None, None)


def _vac_current_rate_disabled():
    import re as _re
    if not vac_save_log_click():
        return _vac_rate_from_window()
    try:
        sz = os.path.getsize(VAC_LOG)
        with open(VAC_LOG, "rb") as f:
            if sz > 16384:
                f.seek(-16384, 2)
            data = f.read().decode("utf-16-le", "replace")
        last = None
        for m in _re.finditer(r"render stream \d+:\s*\w*PCM/(\d{4,6})/", data):
            last = int(m.group(1))
        if last:
            for std in RATES:
                if abs(last - std) < max(300, std * 0.02):
                    LAST_GOOD["panel_dbg"] += f"/logfile:render={std}"
                    return std
    except OSError:
        pass
    return None


def _vac_rate_from_window():
    try:
        import ctypes
        import re as _re
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        k32.VirtualAllocEx.restype = ctypes.c_void_p
        u32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                     wintypes.WPARAM, wintypes.LPARAM]
        u32.SendMessageW.restype = ctypes.c_ssize_t

        mains, lvs = [], []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_top(h, _):
            b = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(h, b, 256)
            if b.value.startswith("Virtual Audio Cable Control Panel"):
                mains.append(h)
            return True

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_child(h, _):
            c = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(h, c, 64)
            if c.value == "SysListView32":
                lvs.append(h)
            return True

        u32.EnumWindows(enum_top, 0)
        LAST_GOOD["panel_dbg"] = f"창{len(mains)}"
        if not mains:
            return None
        u32.EnumChildWindows(mains[0], enum_child, 0)

        class LVITEM(ctypes.Structure):
            _fields_ = [("mask", ctypes.c_uint), ("iItem", ctypes.c_int),
                        ("iSubItem", ctypes.c_int), ("state", ctypes.c_uint),
                        ("stateMask", ctypes.c_uint), ("pszText", ctypes.c_void_p),
                        ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int),
                        ("lParam", ctypes.c_ssize_t), ("iIndent", ctypes.c_int),
                        ("iGroupId", ctypes.c_int), ("cColumns", ctypes.c_uint),
                        ("puColumns", ctypes.c_void_p), ("piColFmt", ctypes.c_void_p),
                        ("iGroup", ctypes.c_int)]

        # 상태 표시줄(하단 Static 라벨)에서 최신 스트림 이벤트 텍스트를 직접 읽는다.
        # 예: "Cable 1, capture stream 289: Terminated ... SR: 48088"
        statics = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_static(h, _):
            c = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(h, c, 64)
            if c.value == "Static":
                b = ctypes.create_unicode_buffer(512)
                u32.GetWindowTextW(h, b, 512)   # 라벨은 자기 프로세스라 바로 읽힘
                if b.value:
                    statics.append(b.value)
            return True

        u32.EnumChildWindows(mains[0], enum_static, 0)
        for s in statics:
            m = _re.search(r"SR:\s*(\d{4,6})", s) or _re.search(r"PCM/(\d{4,6})/", s)
            if m:
                raw = int(m.group(1))
                # 48088 같은 미세 오프셋을 표준 레이트로 스냅
                for std in RATES:
                    if abs(raw - std) < max(300, std * 0.02):
                        LAST_GOOD["panel_dbg"] += f"/status:{raw}->{std}"
                        return std
        LAST_GOOD["panel_dbg"] += f"/static{len(statics)}"

        combos = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_combo(h, _):
            c = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(h, c, 64)
            if c.value in ("ComboBox", "ComboLBox"):
                combos.append(h)
            return True

        u32.EnumChildWindows(mains[0], enum_combo, 0)
        LAST_GOOD["panel_dbg"] += f"/콤보{len(combos)}/리스트{len(lvs)}"

        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(mains[0], ctypes.byref(pid))
        hp = k32.OpenProcess(0x38, False, pid)
        if not hp:
            LAST_GOOD["panel_dbg"] += "/프로세스열기실패(권한)"
            return None
        remote = k32.VirtualAllocEx(hp, None, 4096, 0x3000, 4)
        if not remote:
            k32.CloseHandle(hp)
            return None
        wrote = ctypes.c_size_t()
        found = None

        # 1순위: 이벤트 히스토리 콤보에서 가장 최근의 "Format set to ExtPCM/..." 추출
        #        (렌더 스트림 = TIDAL 소스 레이트의 진실)
        for cb in combos:
            cnt = u32.SendMessageW(cb, 0x0146, 0, 0)  # CB_GETCOUNT
            LAST_GOOD["panel_dbg"] += f"/cnt{cnt}"
            if not cnt or cnt <= 0:
                continue
            if cnt > 100:  # 이벤트 히스토리로 추정 → 진단 덤프 (CB & 내부 LB 동시)
                class CBINFO(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.DWORD),
                                ("rcItem", wintypes.RECT),
                                ("rcButton", wintypes.RECT),
                                ("stateButton", wintypes.DWORD),
                                ("hwndCombo", wintypes.HWND),
                                ("hwndItem", wintypes.HWND),
                                ("hwndList", wintypes.HWND)]
                ci = CBINFO()
                ci.cbSize = ctypes.sizeof(CBINFO)
                ok = u32.GetComboBoxInfo(cb, ctypes.byref(ci))
                dump = [f"GetComboBoxInfo ok={ok} list={ci.hwndList}"]
                for i in range(max(0, cnt - 6), cnt):
                    ln = u32.SendMessageW(cb, 0x0149, i, 0)
                    r1 = u32.SendMessageW(cb, 0x0148, i, remote)
                    b = ctypes.create_unicode_buffer(1000)
                    k32.ReadProcessMemory(hp, ctypes.c_void_p(remote), b, 1900,
                                          ctypes.byref(wrote))
                    t_cb = b.value[:200]
                    t_lb = ""
                    if ci.hwndList:
                        r2 = u32.SendMessageW(ci.hwndList, 0x0189, i, remote)  # LB_GETTEXT
                        b2 = ctypes.create_unicode_buffer(1000)
                        k32.ReadProcessMemory(hp, ctypes.c_void_p(remote), b2, 1900,
                                              ctypes.byref(wrote))
                        t_lb = f" | LB r={r2} :: {b2.value[:200]!r}"
                    dump.append(f"[{i}] len={ln} CB r={r1} :: {t_cb!r}{t_lb}")
                try:
                    with open(os.path.join(HERE, "panel_dump.txt"), "w",
                              encoding="utf-8") as f:
                        f.write("\n".join(dump))
                except OSError:
                    pass
            latest = None
            for i in range(max(0, cnt - 40), cnt):
                ln = u32.SendMessageW(cb, 0x0149, i, 0)  # CB_GETLBTEXTLEN
                if not ln or ln <= 0 or ln > 900:
                    continue
                u32.SendMessageW(cb, 0x0148, i, remote)  # CB_GETLBTEXT
                b = ctypes.create_unicode_buffer(1000)
                k32.ReadProcessMemory(hp, ctypes.c_void_p(remote), b, 1900,
                                      ctypes.byref(wrote))
                m = _re.search(r"render stream \d+: \w*PCM/(\d{4,6})/", b.value)
                if m:
                    latest = int(m.group(1))
            if latest:
                found = latest
                break

        k32.VirtualFreeEx(hp, ctypes.c_void_p(remote), 0, 0x8000)
        k32.CloseHandle(hp)
        return found
    except Exception:
        return None
    return None


def media_playpause():
    """시스템 미디어 키(재생/일시정지) 전송 — SMTC 실패 시 폴백용 (상태 모르는 토글)"""
    try:
        import ctypes
        ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)
    except Exception:
        pass


def _smtc_tidal():
    """TIDAL의 SMTC 미디어 세션 (실측: AUMID='TIDAL.exe'). 없으면 None.
    세션 객체 캐시로 호출당 30-60ms 절약 — 죽으면 자동 재탐색"""
    s = LAST_GOOD.get("smtc")
    if s is not None:
        try:
            s.get_playback_info()
            return s
        except Exception:
            LAST_GOOD["smtc"] = None
    try:
        import asyncio
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as _M)

        async def _get():
            mgr = await _M.request_async()
            for x in mgr.get_sessions():
                if "tidal" in (x.source_app_user_model_id or "").lower():
                    return x
            return None
        s = asyncio.run(_get())
        LAST_GOOD["smtc"] = s
        return s
    except Exception:
        return None


def tidal_playback_status():
    """SMTC 재생 상태: 4=PLAYING, 5=PAUSED, None=판독 불가"""
    s = _smtc_tidal()
    try:
        return int(s.get_playback_info().playback_status) if s else None
    except Exception:
        return None


def tidal_cmd(play):
    """명시적 재생/정지 명령 (토글 아님 → 유실·반전 불가능).
    SMTC 실패 시에만 미디어 키 토글 폴백. 성공 여부 반환"""
    s = _smtc_tidal()
    if s:
        try:
            import asyncio

            async def _go():
                return await (s.try_play_async() if play else s.try_pause_async())
            if asyncio.run(_go()):
                return True
        except Exception:
            pass
    media_playpause()
    return False


def ws_query(cmd):
    try:
        import websocket
        ws = websocket.create_connection(f"ws://127.0.0.1:{WS_PORT}", timeout=2)
        ws.send(json.dumps(cmd))
        res = json.loads(ws.recv())
        ws.close()
        return res
    except Exception:
        return None


def camilla_capture_dbfs():
    res = ws_query("GetCaptureSignalRms")
    try:
        return max(res["GetCaptureSignalRms"]["value"])
    except (TypeError, KeyError):
        return None


def camilla_state():
    res = ws_query("GetState")
    try:
        return res["GetState"]["value"]
    except (TypeError, KeyError):
        return None


def camilla_buffer_level():
    """출력(재생) 버퍼에 실제로 쌓인 프레임 수 — 프라이밍 완료의 실측 지표"""
    res = ws_query("GetBufferLevel")
    try:
        return int(res["GetBufferLevel"]["value"])
    except (TypeError, KeyError, ValueError):
        return None


def wait_pipeline_ready(timeout=1.2):
    """[확정값 1.2s — 2026-08-26 청취 이분탐색 완료] 일시정지 중엔 케이블에 데이터가
    안 흘러 버퍼가 원천적으로 못 참(lvl=0) → 이 대기는 '캡처+ASIO 소비 준비 시간'.
    1.0s 미만: 팝/삼킴 복귀, 1.2s: 깨끗 (잔여 0.1s 잘림은 TIDAL 자체 페이드 = 바닥).
    (lvl>0 관측 시 즉시 재개)"""
    t0 = time.time()
    running = False
    st, lvl = None, None
    while time.time() - t0 < timeout:
        if not running:
            st = camilla_state()
            running = bool(st) and str(st).upper() == "RUNNING"
        if running:
            lvl = camilla_buffer_level()
            if lvl is not None and lvl > 0:
                log(f"재개 준비 완료: 버퍼 {lvl}프레임 ({time.time() - t0:.2f}s)")
                return
        time.sleep(0.05)
    log(f"재개 준비 타임아웃({timeout}s): state={st} lvl={lvl}")


def camilla_error_tail():
    try:
        with open(CAMILLA_LOG, "r", encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        errs = [l for l in lines if "ERROR" in l]
        pick = errs[-2:] if errs else lines[-2:]
        return " | ".join(pick) if pick else "(로그 없음)"
    except OSError:
        return "(로그 읽기 실패)"


def ordered(candidates, remembered):
    if remembered in candidates:
        return [remembered] + [c for c in candidates if c != remembered]
    return list(candidates)


def try_start(rate, expect_signal=True):
    """expect_signal=False: 전환 모드(TIDAL 일시정지 중) — 무신호를 실패로 안 봄"""
    for cap_dev in ordered(CAPTURE_DEVICES, LAST_GOOD["capdev"]):
        for pb_dev in ordered(PLAYBACK_DEVICES, LAST_GOOD["pbdev"]):
            for cap_fmt in ordered(CAPTURE_FORMATS, LAST_GOOD["fmt"]):
                render_config(rate, cap_fmt, cap_dev, pb_dev)
                log(f"기동 시도: {rate}Hz / {cap_fmt} / cap='{cap_dev[:20]}...'")
                lf = open(CAMILLA_LOG, "w", encoding="utf-8")
                proc = subprocess.Popen([CAMILLA_EXE, ACTIVE_PATH, "-p", str(WS_PORT)],
                                        stdout=lf, stderr=subprocess.STDOUT)
                # 빠른 실패 판정 (실패는 0.3초 내 사망 — 성공 대기 최소화)
                dead = False
                for _ in range(4 if not expect_signal else 8):
                    time.sleep(0.15)
                    if proc.poll() is not None:
                        dead = True
                        break
                if dead:
                    lf.close()
                    log(f"  → 실패: {camilla_error_tail()}")
                    continue
                if not expect_signal:
                    # 전환 모드: 프로세스 생존이면 즉시 합격 (신호는 재개 후 확인)
                    LAST_GOOD.update(fmt=cap_fmt, capdev=cap_dev, pbdev=pb_dev)
                    log(f"  → 성공(전환): {rate}Hz / {cap_fmt}")
                    return proc, lf
                # 일반 모드 — 신호 확인 (최대 ~1.2초)
                ok = False
                ws_dead = True
                for _ in range(6):
                    db = camilla_capture_dbfs()
                    if db is not None:
                        ws_dead = False
                        LAST_GOOD["ws_seen"] = True
                        if db > -80:
                            ok = True
                            break
                    time.sleep(0.2)
                # ws_dead 무검증 합격은 '이 세션에서 ws가 한 번도 안 산 경우'만 허용
                # (21:13 사고: 일시정지 중 ws_dead로 S16이 무검증 통과 → 16비트 고착)
                if ok or (ws_dead and not LAST_GOOD.get("ws_seen")):
                    LAST_GOOD.update(fmt=cap_fmt, capdev=cap_dev, pbdev=pb_dev)
                    log(f"  → 성공: {rate}Hz / {cap_fmt}" + (" (웹소켓 미확인)" if ws_dead else ""))
                    return proc, lf
                log("  → 기동됐지만 무신호 (레이트 불일치/일시정지 추정) — 종료 후 다음 후보")
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                time.sleep(0.1)
                lf.close()
    return None, None


def stop(proc, lf):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
    if lf:
        try:
            lf.close()
        except OSError:
            pass
    log("CamillaDSP 종료 — M4 반납 (EqAPO/공유 복귀)")


PID_PATH = os.path.join(HERE, "supervisor.pid")


def kill_previous():
    """이전 수퍼바이저/카밀라 정리 (자기 자신·부모 제외, 검증 후 종료)"""
    import signal
    me, parent = os.getpid(), os.getppid()
    try:
        res = subprocess.run(
            'wmic process where "commandline like \'%%supervisor.py%%\'" get processid',
            shell=True, capture_output=True, text=True, timeout=10)
        pids = [int(t) for t in res.stdout.split() if t.isdigit()]
        for p in pids:
            if p not in (me, parent):
                try:
                    os.kill(p, signal.SIGTERM)
                    log(f"이전 수퍼바이저(pid {p}) 종료")
                except OSError:
                    pass
    except Exception as e:
        log(f"이전 인스턴스 정리 생략: {e}")
    subprocess.run(["taskkill", "/F", "/IM", "camilladsp.exe"],
                   capture_output=True)
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))


def main():
    kill_previous()
    if not os.path.exists(CAMILLA_EXE):
        log(f"camilladsp.exe 없음: {CAMILLA_EXE}")
        sys.exit(1)
    cap_idx = find_capture_index()
    if cap_idx is None:
        log("케이블 캡처 장치 탐색 실패 — --list 확인 필요")
        sys.exit(1)

    _t = vac_current_rate()
    oracle = f"TIDAL 오라클: {_t}Hz" if _t else "TIDAL 오라클: 로그 대기"
    log(f"v1.0 감시 시작 — 케이블 idx {cap_idx} → {PLAYBACK_DEVICES[0]} [{oracle}]")
    proc, lf = None, None
    last_rate = None
    silence_since = None

    try:
        while True:
            if proc is None:
                db = cable_rms_dbfs(cap_idx)
                if db is not None and db > RMS_START_DBFS:
                    # 페이드 꼬리 오탐 방지: 0.3초 뒤에도 신호가 살아있는지 재확인
                    time.sleep(0.3)
                    db2 = cable_rms_dbfs(cap_idx)
                    if db2 is None or db2 <= RMS_START_DBFS:
                        continue
                    # M4가 열거에 안 보이면 프로브로 두드리지 않는다 (장치 플래핑 방지)
                    pb_visible = any(
                        "motu" in d["name"].lower() and d["max_output_channels"] > 0
                        for d in sd.query_devices())
                    if not pb_visible:
                        log("M4 출력이 열거에 없음 — 5초 대기")
                        time.sleep(5)
                        continue
                    lv_rate, lv_pb = vac_lv_info()
                    if lv_pb == 0:
                        # 렌더 0 = TIDAL이 안 밀고 있음 → 헛프로브 방지.
                        # 단 숨김 패널이 스테일일 수 있으므로 신호가 있는 채로
                        # 5회 지속되면 패널 무시하고 프로브 강행 (무음 먹통 방지)
                        LAST_GOOD["pb0_skips"] = LAST_GOOD.get("pb0_skips", 0) + 1
                        if LAST_GOOD["pb0_skips"] % 5 == 1:
                            log(f"신호는 있는데 렌더 스트림 0 — 대기 ({LAST_GOOD['pb0_skips']}회)")
                        if LAST_GOOD["pb0_skips"] < 5:
                            time.sleep(1.0)
                            continue
                        log("렌더 0 지속 + 신호 있음 — 패널 스테일 추정, 프로브 강행")
                    else:
                        LAST_GOOD["pb0_skips"] = 0
                    log(f"재생 감지 ({db:.1f} dBFS) — 프로브 시작")
                    vac_rate = vac_current_rate()
                    if lv_rate:
                        log(f"케이블 실측: {lv_rate}Hz (렌더 {lv_pb}개)")
                    elif vac_rate:
                        log(f"TIDAL 로그 판독: 소스 레이트 {vac_rate}Hz")
                    head = []
                    for r in [lv_rate, vac_rate, last_rate]:
                        if r and r not in head:
                            head.append(r)
                    queue = head + [r for r in RATES if r not in head]
                    tried = set()
                    while queue:
                        # 프로브 중에도 오라클 재확인 — 플러시 지연으로 늦게 온
                        # 진짜 레이트가 있으면 즉시 그쪽으로 점프
                        fresh, fpb = vac_lv_info()
                        if fpb == 0 and LAST_GOOD.get("pb0_skips", 0) < 5:
                            log("렌더 스트림 소멸(일시정지 추정) — 프로브 중단")
                            break
                        if not fresh:
                            fresh = vac_current_rate()
                        if fresh in queue and fresh not in tried:
                            rate = fresh
                        else:
                            rate = queue[0]
                        queue.remove(rate)
                        tried.add(rate)
                        proc, lf = try_start(rate)
                        if proc:
                            last_rate = rate
                            silence_since = None
                            break
                    if proc is None:
                        log("모든 조합 실패 — 15초 냉각")
                        time.sleep(15)
                else:
                    time.sleep(POLL_IDLE_SEC)
            else:
                if proc.poll() is not None:
                    log(f"CamillaDSP 종료됨 (레이트 전환 추정): {camilla_error_tail()} — 재프로브")
                    if lf:
                        lf.close()
                    proc, lf = None, None
                    continue
                # v0.3: 6초마다 VAC 로그에서 소스 레이트 확인 → 변경 시 재기동
                now = time.time()
                if now - LAST_GOOD.get("last_check", 0) > 0.1:
                    LAST_GOOD["last_check"] = now
                    vac_rate = vac_current_rate()
                    lv_rate, _lvpb = vac_lv_info()
                    lv_conf = bool(lv_rate) and lv_rate != last_rate
                    if lv_conf:
                        vac_rate = lv_rate     # 케이블 실측이 로그보다 우선
                    if vac_rate and vac_rate != last_rate and vac_rate in RATES:
                        # 가드 없음: 디코더 오라클/케이블 실측을 항상 신뢰.
                        # (신호 기준 스테일 가드는 VAC 내부 SRC가 불일치 중에도 신호를
                        #  살려두는 탓에 진짜 전환을 영구 기각하는 교착을 만들었음 — 폐기.
                        #  유령 라인의 헛전환은 드물고 다음 라인에서 자가 복구됨)
                        log(f"레이트 전환 감지: {last_rate} → {vac_rate}Hz — TIDAL 일시정지 후 재기동")
                        tidal_cmd(play=False)      # 명시적 정지 (SMTC)
                        # 정지 관철: 곡 시작 직후(CHANGING) 창에서는 명령이 무시됨(실측)
                        # → PAUSED(5) 확인까지 재명령. 그동안 구 체인이 살아 있어
                        #   소리가 계속 나오므로(VAC 내부 SRC) 곡 내용 유실 없음
                        for i in range(10):
                            time.sleep(0.12)
                            stp = tidal_playback_status()
                            if stp is None or stp == 5:
                                break
                            tidal_cmd(play=False)
                            if i == 1:
                                log("정지 미반영 — 반영까지 재명령")
                        stop(proc, lf)
                        proc, lf = try_start(vac_rate, expect_signal=False)
                        if proc:
                            last_rate = vac_rate
                            silence_since = None
                            wait_pipeline_ready()  # Running 확인 즉시 재개
                            tidal_cmd(play=True)   # 명시적 재생 (SMTC)
                            log("TIDAL 재개")
                            LAST_GOOD["resume_check"] = time.time()
                            LAST_GOOD["resume_retry"] = 0
                        else:
                            tidal_cmd(play=True)   # 실패 시에도 재생은 복구
                            log("전환 기동 실패 — TIDAL 재개(구 레이트 경유)")
                        continue
                # 재개 검증(SMTC): 0.8초 후 상태가 PAUSED면 재생 재명령
                # (명시적 명령은 재생 중이면 no-op라 반복해도 무해)
                rc = LAST_GOOD.get("resume_check")
                if rc and now - rc > 0.8:
                    retry = LAST_GOOD.get("resume_retry", 0)
                    stv = tidal_playback_status()
                    if stv == 5 and retry < 3:
                        LAST_GOOD["resume_retry"] = retry + 1
                        tidal_cmd(play=True)
                        log(f"재개 미반영(PAUSED) — 재생 명령 재전송 ({retry + 1}회차)")
                        LAST_GOOD["resume_check"] = now
                    elif stv is None and now - rc < 3.0:
                        pass                       # SMTC 판독 불가 → 3초까지 기다렸다 RMS 폴백
                    elif stv is None:
                        dbv = camilla_capture_dbfs()
                        if dbv is not None and dbv < -70 and retry < 2:
                            LAST_GOOD["resume_retry"] = retry + 1
                            media_playpause()
                            log(f"재개 검증 실패(무신호) — 재생 키 재전송 ({retry + 1}회차)")
                            LAST_GOOD["resume_check"] = now
                        else:
                            LAST_GOOD["resume_check"] = None
                            LAST_GOOD["resume_retry"] = 0
                    else:
                        LAST_GOOD["resume_check"] = None
                        LAST_GOOD["resume_retry"] = 0
                db = camilla_capture_dbfs()
                if db is not None:
                    if db < -70:
                        silence_since = silence_since or time.time()
                        if time.time() - silence_since > SILENCE_STOP_SEC:
                            stop(proc, lf)
                            proc, lf = None, None
                            silence_since = None
                    else:
                        silence_since = None
                time.sleep(0.1)
    except KeyboardInterrupt:
        stop(proc, lf)
        log("수동 종료")


if __name__ == "__main__":
    if "--list" in sys.argv:
        list_devices()
    else:
        try:
            main()
        except Exception:
            import traceback
            log("치명적 오류:\n" + traceback.format_exc())
            time.sleep(2)
            raise
