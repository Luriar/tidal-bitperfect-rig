# -*- coding: utf-8 -*-
"""TIDAL SMTC 제어: py -3 tidal_ctl.py pause|play"""
import asyncio
import sys


async def main(cmd):
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as M)
    mgr = await M.request_async()
    for s in mgr.get_sessions():
        if "tidal" in (s.source_app_user_model_id or "").lower():
            if cmd == "pause":
                return await s.try_pause_async()
            return await s.try_play_async()
    return False


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "pause"
    print(asyncio.run(main(c)))
