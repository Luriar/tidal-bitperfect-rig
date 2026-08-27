# -*- coding: utf-8 -*-
"""TIDAL SMTC 상태 판독: 4=PLAYING 5=PAUSED"""
import asyncio
import os

HERE = os.path.dirname(os.path.abspath(__file__))


async def main():
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as M)
    mgr = await M.request_async()
    for s in mgr.get_sessions():
        if "tidal" in (s.source_app_user_model_id or "").lower():
            st = int(s.get_playback_info().playback_status)
            t = ""
            try:
                p = await s.try_get_media_properties_async()
                t = p.title
            except Exception:
                pass
            return f"status={st} (4=PLAYING 5=PAUSED) title={t!r}"
    return "TIDAL 세션 없음 (앱 꺼짐?)"


with open(os.path.join(HERE, "tidal_status.txt"), "w", encoding="utf-8") as f:
    try:
        f.write(asyncio.run(main()))
    except Exception:
        import traceback
        f.write(traceback.format_exc())
