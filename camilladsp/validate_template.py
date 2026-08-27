# -*- coding: utf-8 -*-
"""모든 음감 템플릿 사전 검증: 더미 값으로 렌더 후 camilladsp --check"""
import glob
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
targets = sorted(glob.glob(os.path.join(HERE, "music_*.yml")))
targets.append(os.path.join(HERE, "config_template.yml"))
lines = []
RES_BLOCK = ("  capture_samplerate: 192000\n"
             "  enable_rate_adjust: true\n"
             "  resampler:\n"
             "    type: AsyncSinc\n"
             "    profile: Accurate\n")


def render(raw, hires):
    return (raw
            .replace("{{RATE}}", "44100")
            .replace("{{MOBIUS_RATE}}", "96000" if hires else "44100")
            .replace("{{MOBIUS_RESAMPLE}}\n", RES_BLOCK if hires else "")
            .replace("{{CAPTURE_DEVICE}}", "Line 1(Virtual Audio Cable)")
            .replace("{{PLAYBACK_DEVICE}}", "MOTU M Series")
            .replace("{{CAPTURE_FORMAT}}", "S24"))


for t in targets:
    with open(t, encoding="utf-8") as f:
        raw = f.read()
    variants = [(False, "")]
    if "{{MOBIUS_RATE}}" in raw:
        variants = [(False, " (native)"), (True, " (hires-resample)")]
    for hires, tag in variants:
        vp = os.path.join(HERE, "config_validate.yml")
        with open(vp, "w", encoding="utf-8") as f:
            f.write(render(raw, hires))
        r = subprocess.run([os.path.join(HERE, "camilladsp.exe"), "--check", vp],
                           capture_output=True, text=True, timeout=20)
        verdict = "OK" if r.returncode == 0 else "FAIL"
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] if r.returncode else []
        lines.append(f"[{verdict}] {os.path.basename(t)}{tag}" +
                     (f" :: {tail[0][:150]}" if tail else ""))
with open(os.path.join(HERE, "validate_out.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done")
