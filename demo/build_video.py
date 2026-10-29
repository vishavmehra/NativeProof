"""Assemble the narrated walkthrough from the raw screen recordings in demo/raw.

Each segment gets a title card, a synthetic voiceover (edge-tts), burned-in captions, and a label with the real
elapsed time and the playback speed whenever footage is sped up. Requires ffmpeg on PATH and `uvx` (edge-tts).
Usage: python demo/build_video.py
"""

import json
import subprocess
import time
from pathlib import Path

DEMO = Path(__file__).resolve().parent
RAW, OUT = DEMO / "raw", DEMO / "build"
VOICE = "en-US-AndrewMultilingualNeural"
W, H, VH = 1600, 900, 812  # frame, then the video area above the caption bar
FONT = "C\\:/Windows/Fonts/segoeui.ttf"
FONT_BOLD = "C\\:/Windows/Fonts/segoeuib.ttf"
BG = "0x0f172a"

SEGMENTS = json.loads((DEMO / "segments.json").read_text(encoding="utf-8"))


def run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def voiceover(name: str, text: str) -> tuple[Path, Path, float]:
    mp3, vtt = OUT / f"{name}.mp3", OUT / f"{name}.vtt"
    for attempt in range(4):  # the TTS service occasionally drops a request
        if mp3.exists() and vtt.exists() and mp3.stat().st_size > 0:
            break
        try:
            run(["uvx", "--quiet", "edge-tts", "--voice", VOICE, "--text", text,
                 "--write-media", str(mp3), "--write-subtitles", str(vtt)])
        except subprocess.CalledProcessError:
            mp3.unlink(missing_ok=True)
            vtt.unlink(missing_ok=True)
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    return mp3, vtt, duration(mp3)


def subtitle_filter(vtt: Path) -> str:
    path = str(vtt).replace("\\", "/").replace(":", "\\:")
    style = "FontName=Segoe UI,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=0,Shadow=0,MarginV=6"
    return f"subtitles='{path}':force_style='{style}'"


def card(name: str, title: str, subtitle: str, seconds: float, audio: Path | None = None, vtt: Path | None = None) -> Path:
    out = OUT / f"{name}.mp4"
    draw = (f"drawtext=fontfile='{FONT_BOLD}':text='{esc(title)}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=h/2-90,"
            f"drawtext=fontfile='{FONT}':text='{esc(subtitle)}':fontcolor=0xcbd5e1:fontsize=28:x=(w-text_w)/2:y=h/2+10")
    if vtt:
        draw += "," + subtitle_filter(vtt)
    inputs = ["-f", "lavfi", "-i", f"color=c={BG}:s={W}x{H}:d={seconds}:r=30"]
    inputs += ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={seconds}"]
    run(["ffmpeg", "-y", *inputs, "-vf", draw, "-t", f"{seconds:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-r", "30", "-c:a", "aac", "-ar", "24000", "-ac", "1", "-shortest", str(out)])
    return out


def clip(seg: dict, audio: Path, vtt: Path, target: float) -> Path:
    out = OUT / f"{seg['name']}.mp4"
    sources = [RAW / f for f in seg["files"]]
    raw_total = sum(duration(s) for s in sources)
    factor = max(1.0, raw_total / target)
    seg["real_seconds"], seg["speed"] = round(raw_total, 1), round(factor, 2)
    if out.exists() and out.stat().st_size > 0:  # already built by an earlier run
        return out
    label = f"Real time {int(raw_total // 60)}:{int(raw_total % 60):02d}" + (f" · shown at {factor:.1f}x" if factor > 1.05 else "")
    parts = []
    for i in range(len(sources)):
        parts.append(f"[{i}:v]fps=30,scale={W}:{VH}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{VH}:(ow-iw)/2:0:color={BG},setsar=1[v{i}]")
    chain = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(sources)))
    chain += f"concat=n={len(sources)}:v=1:a=0[cat];[cat]setpts=PTS/{factor:.4f},tpad=stop_mode=clone:stop_duration=30,"
    chain += (f"pad={W}:{H}:0:0:color={BG},"
              f"drawtext=fontfile='{FONT}':text='{esc(label)}':fontcolor=white:fontsize=22:box=1:boxcolor=0x0f172acc:"
              f"boxborderw=10:x=w-text_w-24:y=20,"
              f"drawtext=fontfile='{FONT_BOLD}':text='{esc(seg['title'])}':fontcolor=white:fontsize=22:box=1:"
              f"boxcolor=0x4f46e5dd:boxborderw=10:x=24:y=20,"
              f"{subtitle_filter(vtt)}[v]")
    args = ["ffmpeg", "-y"]
    for s in sources:
        args += ["-i", str(s)]
    args += ["-i", str(audio), "-filter_complex", chain, "-map", "[v]", "-map", f"{len(sources)}:a",
             "-t", f"{target:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p",
             "-r", "30", "-c:a", "aac", "-ar", "24000", "-ac", "1", str(out)]
    run(args)
    seg["real_seconds"], seg["speed"] = round(raw_total, 1), round(factor, 2)
    return out


def srt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    pieces, captions, clock, n = [], [], 0.0, 1
    for seg in SEGMENTS:
        audio, vtt, spoken = voiceover(seg["name"], seg["narration"])
        target = spoken + 1.2
        if seg.get("card_only"):
            video = card(seg["name"], seg["title"], seg["subtitle"], target, audio, vtt)
        else:
            pieces.append(card(seg["name"] + "-card", seg["title"], seg["subtitle"], 2.5))
            clock += 2.5
            video = clip(seg, audio, vtt, target)
        pieces.append(video)
        for block in vtt.read_text(encoding="utf-8").split("\n\n"):
            lines = [l for l in block.strip().splitlines() if l.strip()]
            if len(lines) >= 2 and "-->" in lines[-2]:
                start, end = [x.strip() for x in lines[-2].split("-->")]
                to_s = lambda ts: sum(float(p) * 60 ** i for i, p in enumerate(reversed(ts.replace(",", ".").split(":"))))
                captions.append(f"{n}\n{srt_time(clock + to_s(start))} --> {srt_time(clock + to_s(end))}\n{lines[-1]}\n")
                n += 1
        clock += target
    listing = OUT / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces), encoding="utf-8")
    final = DEMO / "nativeproof-walkthrough.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(final)])
    (DEMO / "captions.srt").write_text("\n".join(captions), encoding="utf-8")
    (DEMO / "timings.json").write_text(json.dumps([{k: s.get(k) for k in ("name", "title", "real_seconds", "speed")}
                                                   for s in SEGMENTS], indent=2), encoding="utf-8")
    print(f"wrote {final} ({duration(final):.0f}s, {final.stat().st_size / 1e6:.1f} MB) and captions.srt")


if __name__ == "__main__":
    main()
