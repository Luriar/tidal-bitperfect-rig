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
import threading

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
RATE_STABLE_SEC = 0.20     # metadata-only fallback; matched TIDAL+VAC switches immediately
RATE_STABLE_POLLS = 2      # metadata-only fallback polls
RATE_FALLBACK_STABLE_SEC = 0.50  # VAC-only fallback stays conservative
# =================================

LAST_GOOD = {"fmt": None, "capdev": None, "pbdev": None}

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(HERE, "config_template.yml")
ACTIVE_PATH = os.path.join(HERE, "config_active.yml")
LOG_PATH = os.path.join(HERE, "supervisor.log")
CAMILLA_LOG = os.path.join(HERE, "camilla_last.log")
CLOCK_SCRIPT = os.path.join(HERE, "audio-clock-mode.ps1")


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
    """Return activity without opening a Windows capture stream.

    VAC exposes the current stream count in its control panel (control id 1024).
    Reading that Static control does not open the capture endpoint, so Windows
    microphone privacy state stays untouched. Keep the old dB-shaped return
    values because the main loop only compares them with RMS_START_DBFS.
    """
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        mains = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_top(h, _):
            b = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(h, b, 256)
            if b.value.startswith("Virtual Audio Cable Control Panel"):
                mains.append(h)
            return True

        u32.EnumWindows(enum_top, 0)
        if not mains:
            _lv_init()
            return None

        # vcctlpan ignores STARTUPINFO SW_HIDE on some builds. Force-hide it.
        try:
            u32.ShowWindow(mains[0], 0)
        except Exception:
            pass

        streams_ctl = u32.GetDlgItem(mains[0], 1024)
        if not streams_ctl:
            return None
        b = ctypes.create_unicode_buffer(32)
        u32.GetWindowTextW(streams_ctl, b, 32)
        value = b.value.strip()
        if not value.isdigit():
            return None
        return -20.0 if int(value) > 0 else -120.0
    except Exception:
        return None

def render_config(rate, cap_fmt, cap_dev, pb_dev):
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        cfg = f.read()
    # 모비우스 모드용 조건 렌더: ≤96k는 네이티브 그대로, >96k만 96k로 정밀 리샘플
    # Native-rate playback: follow the TIDAL source rate on MOTU ASIO.
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
                    # VAC may ignore SW_HIDE. Hide its top-level window as soon as it exists.
                    for _ in range(20):
                        time.sleep(0.05)
                        mains.clear()
                        u32.EnumWindows(et, 0)
                        if mains:
                            u32.ShowWindow(mains[0], 0)
                            break
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
    """Send an explicit TIDAL SMTC play/pause command.

    Never fall back to the system Play/Pause toggle here. A toggle is unsafe when
    playback state is unknown and was the source of repeated transport flips.
    """
    current = tidal_playback_status()
    if (play and current == 4) or ((not play) and current == 5):
        return True
    s = _smtc_tidal()
    if not s:
        return False
    try:
        import asyncio

        async def _go():
            return await (s.try_play_async() if play else s.try_pause_async())
        return bool(asyncio.run(_go()))
    except Exception:
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
        values = res["GetCaptureSignalRms"]["value"]
        if not values:
            return None
        return max(values)
    except (TypeError, KeyError, ValueError):
        return None


def camilla_state():
    res = ws_query("GetState")
    try:
        return res["GetState"]["value"]
    except (TypeError, KeyError):
        return None


def camilla_set_mute(muted):
    """Set CamillaDSP Main mute explicitly; never toggle."""
    res = ws_query({"SetMute": bool(muted)})
    try:
        return res["SetMute"]["result"] == "Ok"
    except (TypeError, KeyError):
        return False


def seek_declick_worker():
    """Hide TIDAL seek discontinuities without touching transport state.

    On media.seek, mute immediately. Keep output muted across TIDAL's exclusive
    WASAPI teardown/reopen and only unmute after the NEW render thread has
    actually started, plus a short settling window. A timeout prevents stuck mute.
    """
    import re as _re
    pos = None
    seek_re = _re.compile(r'"command"\s*:\s*"media\.seek"')
    render_re = _re.compile(r'WASAPI engine starting render thread', _re.I)
    pending = False
    render_seen_at = None
    seek_started_at = 0.0
    while True:
        try:
            now = time.time()
            size = os.path.getsize(TIDAL_LOG)
            data = ""
            if pos is None or size < pos:
                pos = size  # start at EOF; never replay historical seeks
            elif size > pos:
                with open(TIDAL_LOG, "rb") as f:
                    f.seek(pos)
                    data = f.read(size - pos).decode("utf-8", "replace")
                pos = size

            if data and seek_re.search(data):
                pending = True
                render_seen_at = None
                seek_started_at = now
                if camilla_set_mute(True):
                    log("seek de-click v2: mute immediately")

            if pending and data and render_re.search(data):
                render_seen_at = now
                log("seek de-click v2: new WASAPI render thread seen")

            # Let the new render callback fill a few 256-sample chunks before
            # exposing it. 60 ms covers the observed TIDAL seek reopen window.
            if pending and render_seen_at is not None and now - render_seen_at >= 0.06:
                camilla_set_mute(False)
                log("seek de-click v2: unmute after render settle")
                pending = False
                render_seen_at = None
            elif pending and now - seek_started_at >= 1.5:
                camilla_set_mute(False)
                log("seek de-click v2: timeout unmute")
                pending = False
                render_seen_at = None

            time.sleep(0.01)
        except Exception:
            # Never leave output muted if the log rolls or Camilla restarts.
            if pending:
                try:
                    camilla_set_mute(False)
                except Exception:
                    pass
                pending = False
                render_seen_at = None
            time.sleep(0.05)

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


def set_clock_mode(rate, shared=False):
    """Coordinate Windows endpoints, MOTU hardware clock and Light Host."""
    if LAST_GOOD.get("clock_rate") == rate and LAST_GOOD.get("clock_shared") == shared:
        return True
    args = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", CLOCK_SCRIPT, "-Rate", str(rate),
    ]
    if shared:
        args.append("-Shared")
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            log(f"clock mode failed rate={rate} shared={shared}: {(r.stderr or r.stdout)[-400:]}")
            return False
        LAST_GOOD["clock_rate"] = rate
        LAST_GOOD["clock_shared"] = shared
        log(f"clock mode -> {'shared' if shared else 'native'} {rate}Hz")
        return True
    except Exception as e:
        log(f"clock mode exception rate={rate} shared={shared}: {e}")
        return False


def prepare_native_rate(rate):
    ps = (
        "Get-Process 'Light Host' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; "
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'wscript.exe' -and $_.CommandLine -like '*light-host-autostart.vbs*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],
                       capture_output=True,text=True,timeout=5,
                       creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    except Exception as e:
        log(f"native prep Light Host cleanup skipped: {e}")
    LAST_GOOD["clock_rate"] = rate
    LAST_GOOD["clock_shared"] = False
    log(f"native prep -> ASIO owns {rate}Hz; WDM forcing disabled")
    return True


def restore_shared_48():
    return set_clock_mode(48000, shared=True)


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
                checks = 4 if not expect_signal else 8
                delay = 0.05 if not expect_signal else 0.15
                for _ in range(checks):
                    time.sleep(delay)
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
    """Stop only the previously recorded supervisor PID and camilladsp.exe."""
    me = os.getpid()
    old = None
    try:
        with open(PID_PATH, "r", encoding="utf-8") as f:
            old = int(f.read().strip())
    except Exception:
        old = None

    if old and old != me:
        try:
            ps_cmd = (
                "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%d'; "
                "if($p){$p.Name + '|' + $p.CommandLine}" % old
            )
            check = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            info = (check.stdout or "")
            if "supervisor.py" in info and ("py.exe|" in info or "python.exe|" in info):
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(old)],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                log(f"previous supervisor stopped (pid {old})")
        except Exception as e:
            log(f"previous supervisor cleanup skipped: {e}")

    subprocess.run(
        ["taskkill", "/F", "/IM", "camilladsp.exe"],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with open(PID_PATH, "w", encoding="utf-8") as f:
        f.write(str(me))


# TIDAL_GATE_ONLY_V1
def tidal_process_running():
    """Return True only while TIDAL.exe exists. No clock restore side effects."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq TIDAL.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=1.5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "TIDAL.exe" in (r.stdout or "")
    except Exception:
        return False


def main():
    kill_previous()
    threading.Thread(target=seek_declick_worker, name="tidal-seek-declick", daemon=True).start()
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
    pending_rate = None
    pending_rate_since = 0.0
    pending_rate_hits = 0
    if not tidal_process_running():
        restore_shared_48()
    else:
        _vr = vac_current_rate()
        _lv, _pb = vac_lv_info()
        _native = _lv or _vr
        if _native in RATES and _pb:
            prepare_native_rate(_native)
        else:
            log("TIDAL active at startup -> defer shared 48 restore until native rate resolves")

    try:
        while True:
            # TIDAL_GATE_ONLY_V1: never probe/open MOTU ASIO for unrelated
            # Line 1 senders while TIDAL itself is not running.
            if not tidal_process_running():
                # Quarantine decoder metadata from the previous TIDAL session.
                # Keep the current EOF so a later launch only sees newly appended
                # decoder metadata instead of reusing the last track's rate.
                try:
                    LAST_GOOD["tlog_pos"] = os.path.getsize(TIDAL_LOG)
                except OSError:
                    LAST_GOOD.pop("tlog_pos", None)
                LAST_GOOD.pop("tlog_rate", None)
                if proc is not None:
                    log("TIDAL absent -> stop CamillaDSP and stay idle")
                    stop(proc, lf)
                    proc, lf = None, None
                    silence_since = None
                    last_rate = None
                if not LAST_GOOD.get("clock_shared"):
                    restore_shared_48()
                time.sleep(0.5)
                continue

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
                        # No active VAC sender: stay idle; never force-open MOTU ASIO.
                        LAST_GOOD["pb0_skips"] = LAST_GOOD.get("pb0_skips", 0) + 1
                        if LAST_GOOD["pb0_skips"] % 5 == 1:
                            log(f"VAC sender 0 -> idle, probe suppressed ({LAST_GOOD['pb0_skips']})")
                        time.sleep(1.0)
                        continue
                    else:
                        LAST_GOOD["pb0_skips"] = 0
                    log(f"재생 감지 ({db:.1f} dBFS) — 프로브 시작")
                    vac_rate = vac_current_rate()
                    if lv_rate:
                        log(f"케이블 실측: {lv_rate}Hz (렌더 {lv_pb}개)")
                    elif vac_rate:
                        log(f"TIDAL 로그 판독: 소스 레이트 {vac_rate}Hz")
                    # Never sweep the MOTU hardware clock across guessed sample rates.
                    # Use live VAC/TIDAL metadata only. If the rate is temporarily
                    # unknown, wait instead of changing hardware clock.
                    head = []
                    for r in (lv_rate, vac_rate):
                        if r and r in RATES and r not in head:
                            head.append(r)
                    if not head and last_rate in RATES:
                        head = [last_rate]

                    if not head:
                        log("VAC rate unresolved -> wait; hardware rate sweep suppressed")
                        time.sleep(0.5)
                        continue

                    queue = list(head)
                    tried = set()
                    while queue:
                        fresh, fpb = vac_lv_info()
                        if fpb == 0 and LAST_GOOD.get("pb0_skips", 0) < 5:
                            log("VAC sender disappeared during start -> wait")
                            break
                        if not fresh:
                            fresh = vac_current_rate()

                        if fresh in RATES and fresh not in tried:
                            rate = fresh
                            if rate in queue:
                                queue.remove(rate)
                            else:
                                queue = []
                        else:
                            rate = queue.pop(0)

                        tried.add(rate)
                        if not prepare_native_rate(rate):
                            log(f"native clock prepare failed: {rate}Hz")
                            break

                        known_rate = rate in [r for r in (lv_rate, vac_rate, fresh) if r]
                        proc, lf = try_start(rate, expect_signal=not known_rate)
                        if proc:
                            last_rate = rate
                            silence_since = None
                            if known_rate:
                                wait_pipeline_ready()
                                resumed = tidal_cmd(play=True)
                                log(f"known VAC rate {rate}Hz -> pipeline ready, TIDAL resume "
                                    f"{'ok' if resumed else 'unavailable'}")
                            break

                    if proc is None:
                        # Keep the known native clock while TIDAL is present.
                        # Do not bounce to shared 48k and do not scan unrelated rates.
                        log("known-rate start failed -> keep clock, retry in 1s")
                        time.sleep(1.0)
                else:
                    time.sleep(POLL_IDLE_SEC)
            else:
                if proc.poll() is not None:
                    log(f"CamillaDSP 종료됨 (레이트 전환 추정): {camilla_error_tail()} — 재프로브")
                    if lf:
                        lf.close()
                    proc, lf = None, None
                    if not tidal_process_running():
                        restore_shared_48()
                    else:
                        log("Camilla exited while TIDAL active -> keep native clock and retry")
                        time.sleep(0.5)
                    continue
                # v0.3: 6초마다 VAC 로그에서 소스 레이트 확인 → 변경 시 재기동
                now = time.time()
                if now - LAST_GOOD.get("last_check", 0) > 0.1:
                    LAST_GOOD["last_check"] = now
                    tlog_rate = vac_current_rate()
                    lv_rate, lv_pb = vac_lv_info()

                    # Hot-switch policy:
                    # TIDAL metadata can be preloaded, and VAC live rate can flap
                    # briefly during seek. Switch immediately only when both agree;
                    # otherwise use conservative fallbacks. TIDAL transport itself
                    # is never paused/resumed for a rate change.
                    candidate = None
                    candidate_source = None
                    if lv_pb != 0:
                        if tlog_rate in RATES and lv_rate == tlog_rate:
                            candidate = tlog_rate
                            candidate_source = "TIDAL+VAC"
                        elif tlog_rate in RATES and lv_rate is None:
                            candidate = tlog_rate
                            candidate_source = "TIDAL metadata"
                        elif lv_rate in RATES and tlog_rate not in RATES:
                            candidate = lv_rate
                            candidate_source = "VAC live fallback"
                        # Known-but-disagreeing sources mean preload/transient: hold.

                    if candidate and candidate != last_rate:
                        if candidate != pending_rate:
                            pending_rate = candidate
                            pending_rate_since = now
                            pending_rate_hits = 1
                            log(f"rate candidate: {last_rate} -> {candidate}Hz ({candidate_source})")
                        else:
                            pending_rate_hits += 1

                        stable_for = now - pending_rate_since
                        if candidate_source == "TIDAL+VAC":
                            required_stable, required_hits = 0.0, 1
                        elif candidate_source == "TIDAL metadata":
                            required_stable, required_hits = RATE_STABLE_SEC, RATE_STABLE_POLLS
                        else:
                            required_stable, required_hits = RATE_FALLBACK_STABLE_SEC, 3

                        if stable_for >= required_stable and pending_rate_hits >= required_hits:
                            target_rate = candidate
                            log(f"hot sample-rate switch: {last_rate} -> {target_rate}Hz "
                                f"({candidate_source}, {stable_for:.2f}s/{pending_rate_hits} polls); "
                                "TIDAL transport untouched")
                            stop(proc, lf)
                            if not prepare_native_rate(target_rate):
                                proc, lf = None, None
                            else:
                                proc, lf = try_start(target_rate, expect_signal=False)

                            if proc:
                                last_rate = target_rate
                                silence_since = None
                                log("hot-switch pipeline running; playback continues without pause/resume")
                            else:
                                log("hot-switch start failed; TIDAL left playing, normal start path will recover")

                            pending_rate = None
                            pending_rate_since = 0.0
                            pending_rate_hits = 0
                            continue
                    else:
                        # Same rate, source disagreement, unknown rate, or sender gap
                        # (seek): never restart the pipeline and never carry a partial
                        # candidate across the gap.
                        pending_rate = None
                        pending_rate_since = 0.0
                        pending_rate_hits = 0
                db = camilla_capture_dbfs()
                if db is not None:
                    if db < -70:
                        silence_since = silence_since or time.time()
                        if time.time() - silence_since > SILENCE_STOP_SEC:
                            stop(proc, lf)
                            proc, lf = None, None
                            silence_since = None
                            last_rate = None
                            restore_shared_48()
                    else:
                        silence_since = None
                time.sleep(0.1)
    except KeyboardInterrupt:
        stop(proc, lf)
        restore_shared_48()
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
