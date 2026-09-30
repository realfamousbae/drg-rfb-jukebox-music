#!/usr/bin/env python3
"""Find each track from data/playlist.tsv on YouTube, download best audio and convert it to WAV in tracks/.

    python tools/fetch_tracks.py --dry-run        # only show which video was picked for each track
    python tools/fetch_tracks.py [--only 3 7]     # download + convert (skips tracks whose WAV already exists)
    python tools/fetch_tracks.py --url 3=https://youtu.be/...   # force a specific video for track 3

playlist.tsv columns: artists, title, duration (m:ss, as shown in Spotify), url (optional).
A filled url pins the approved video; an empty one means "search YouTube" - after checking the pick with
--dry-run, paste its URL into the row so every machine downloads the same version.
Row N becomes "NN Artist - Title.wav".
Sources (.webm/.m4a from yt-dlp -f ba) are kept in tracks/_src/. Requires yt-dlp and ffmpeg on PATH.
"""
import argparse
import csv
import re
import subprocess
from pathlib import Path

from common import REPO

PLAYLIST = REPO / "data" / "playlist.tsv"
TRACKS_DIR = REPO / "tracks"
SRC_DIR = TRACKS_DIR / "_src"
SEARCH_N = 10
BAD_WORDS = ("remix", "speed", "sped", "slowed", "reverb", "reaction", "реакция", "разбор", "breakdown",
             "cover", "кавер", "karaoke", "караоке", "instrumental", "минус", "live", "лайв", "концерт",
             "8d", "nightcore", "bass boost", "mashup", "мэшап", "tiktok", "1 hour", "1 час")


def seconds(mmss):
    m, s = mmss.split(":")
    return int(m) * 60 + int(s)


def safe_name(text):
    return re.sub(r'[<>:"/\\|?*]', "_", text).strip(" .")


def load_playlist():
    with PLAYLIST.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return [{"n": i, "artists": [a.strip() for a in r["artists"].split(",")], "title": r["title"].strip(),
             "duration": seconds(r["duration"]), "url": (r.get("url") or "").strip()}
            for i, r in enumerate(rows, 1)]


def search(track):
    query = f"{' '.join(track['artists'])} {track['title']}"
    out = subprocess.run(["yt-dlp", "--flat-playlist", "--print", "%(id)s\t%(duration)s\t%(channel)s\t%(title)s",
                          f"ytsearch{SEARCH_N}:{query}"], capture_output=True, text=True, encoding="utf-8")
    results = []
    for line in out.stdout.splitlines():
        vid, dur, channel, title = (line.split("\t", 3) + ["", "", ""])[:4]
        try:
            dur = float(dur)
        except ValueError:
            continue
        results.append({"id": vid, "duration": dur, "channel": channel, "title": title})
    return results


def score(track, r):
    """Lower is better. Duration match dominates; artist channel / Topic and a clean title break ties."""
    low_title, low_channel = r["title"].lower(), r["channel"].lower()
    diff = abs(r["duration"] - track["duration"])
    s = diff if diff <= 4 else 20 + diff
    if any(w in low_title and w not in track["title"].lower() for w in BAD_WORDS):
        s += 100
    if track["title"].lower() not in low_title:
        s += 30
    if any(a.lower() in low_channel for a in track["artists"]) or low_channel.endswith("- topic"):
        s -= 3
    return s


def pick(track):
    results = search(track)
    if not results:
        return None, None
    best = min(results, key=lambda r: score(track, r))
    return best, score(track, best)


class StepFailed(Exception):
    pass


def run(cmd):
    if subprocess.run(cmd).returncode != 0:
        raise StepFailed(cmd[0])


def download_and_convert(track, url, wav):
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    stem = wav.stem
    # 1. source: best audio as is (usually .webm/opus)
    run(["yt-dlp", "--remote-components", "ejs:github", "-f", "ba", "--no-playlist",
         "-o", str(SRC_DIR / f"{stem}.%(ext)s"), url])
    src = next((p for p in SRC_DIR.glob(f"{glob_escape(stem)}.*") if p.suffix != ".part"), None)
    if not src:
        raise StepFailed("yt-dlp produced no file")
    # 2. WAV 24-bit / 48 kHz
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn",
         "-c:a", "pcm_s24le", "-ar", "48000", str(wav)])


def glob_escape(text):
    return re.sub(r"([\[\]*?])", r"[\1]", text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="only print the chosen videos")
    ap.add_argument("--only", type=int, nargs="+", metavar="N", help="process only these playlist rows")
    ap.add_argument("--url", action="append", default=[], metavar="N=URL", help="use this video for row N")
    ap.add_argument("--force", action="store_true", help="re-download even if the WAV exists")
    args = ap.parse_args()

    forced = {}
    for item in args.url:
        n, _, url = item.partition("=")
        forced[int(n)] = url
    tracks = [t for t in load_playlist() if not args.only or t["n"] in args.only]
    doubtful, failed = [], []
    for t in tracks:
        name = safe_name(f"{t['n']:02d} {', '.join(t['artists'])} - {t['title']}")
        wav = TRACKS_DIR / f"{name}.wav"
        if wav.exists() and not args.force and not args.dry_run:
            print(f"[{t['n']:02d}] exists, skip: {wav.name}")
            continue
        if t["n"] in forced:
            url, info = forced[t["n"]], "(forced URL)"
        elif t["url"]:
            url, info = t["url"], "(pinned in playlist.tsv)"
        else:
            best, s = pick(t)
            if not best:
                doubtful.append(t["n"])
                print(f"[{t['n']:02d}] NOT FOUND: {name}")
                continue
            url = f"https://www.youtube.com/watch?v={best['id']}"
            flag = "" if s <= 4 else "  <-- CHECK"
            if flag:
                doubtful.append(t["n"])
            info = (f"{best['duration']:.0f}s vs {t['duration']}s  [{best['channel']}] {best['title']}{flag}")
        print(f"[{t['n']:02d}] {name}\n     {url}  {info}")
        if not args.dry_run:
            try:
                download_and_convert(t, url, wav)
            except StepFailed as e:
                failed.append(t["n"])
                print(f"[{t['n']:02d}] FAILED ({e}), skipped")
    if failed:
        print(f"\nFailed (age-restricted/unavailable? give another URL with --url N=...): {' '.join(map(str, failed))}")
    if doubtful:
        print(f"\nCheck these rows manually (use --url N=...): {' '.join(map(str, doubtful))}")


if __name__ == "__main__":
    main()
