#!/usr/bin/env python3
"""Convert your tracks to WAV, level their loudness and lay them out under the jukebox slot names.

    python tools/prepare_tracks.py measure path/to/vanilla_export.ogg ...   # LUFS / true peak of any files
    python tools/prepare_tracks.py build [--target-lufs -11] [--trim-silence] [--order shuffle]

build reads tracks/ and data/jukebox_slots.csv (+ optional data/mapping.csv) and writes
build/import/<Audio/Music/JukeBox/...>/<SlotName>.wav plus build/import/manifest.csv for ue_import.py.
Each set of slots (normal and streamer) cycles through all tracks independently.
Requires ffmpeg and ffprobe on PATH.
"""
import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from common import (IMPORT_DIR, MANIFEST_CSV, MAPPING_CSV, REPO, BUILD, WAVE_PROPS, die, load_slots,
                    read_csv, write_csv)

TRACKS_DIR = REPO / "tracks"
NORMALIZED_DIR = BUILD / "normalized"
AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a", ".aac", ".aif", ".aiff", ".wma"}
MANIFEST_FIELDS = ["asset_path", "wav", "track", "set", "duration_sec", "output_lufs"] + WAVE_PROPS

TRIM_FILTER = ("silenceremove=start_periods=1:start_threshold=-60dB:start_silence=0.05,"
               "areverse,"
               "silenceremove=start_periods=1:start_threshold=-60dB:start_silence=0.3,"
               "areverse")


def run_ffmpeg(args):
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        die(f"ffmpeg failed ({' '.join(args[:3])} ...):\n{proc.stderr[-2000:]}")
    return proc.stderr


def last_json(text):
    """loudnorm prints its JSON report as a {...} block in stderr (not always the last lines)."""
    blocks = [b for b in re.findall(r"\{[^{}]*\}", text) if '"input_i"' in b]
    if not blocks:
        die("could not parse loudnorm output from ffmpeg")
    return json.loads(blocks[-1])


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def measure(files):
    for f in files:
        stats = last_json(run_ffmpeg(["-i", str(f), "-af", "loudnorm=print_format=json", "-f", "null", "-"]))
        print(f"{stats['input_i']:>7} LUFS  {stats['input_tp']:>6} dBTP  "
              f"LRA {stats['input_lra']:>5}  {probe_duration(f):7.1f}s  {f}")


def normalize(src, dst, target_lufs, true_peak, sample_rate, trim):
    """Two-pass EBU R128 loudnorm; returns the loudnorm report of the second pass."""
    pre = TRIM_FILTER + "," if trim else ""
    target = f"I={target_lufs}:TP={true_peak}:LRA=20"
    first = last_json(run_ffmpeg(["-i", str(src), "-af", f"{pre}loudnorm={target}:print_format=json",
                                  "-f", "null", "-"]))
    measured = (f"measured_I={first['input_i']}:measured_TP={first['input_tp']}:"
                f"measured_LRA={first['input_lra']}:measured_thresh={first['input_thresh']}:"
                f"offset={first['target_offset']}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp.wav")
    second = last_json(run_ffmpeg([
        "-y", "-i", str(src), "-vn", "-map_metadata", "-1",
        "-af", f"{pre}loudnorm={target}:{measured}:linear=true:print_format=json",
        "-ar", str(sample_rate), "-ac", "2", "-c:a", "pcm_s16le", str(tmp)]))
    tmp.replace(dst)
    return second


def cache_key(src, args):
    st = src.stat()
    raw = f"{src.name}|{st.st_size}|{st.st_mtime_ns}|{args.target_lufs}|{args.true_peak}|" \
          f"{args.sample_rate}|{args.trim_silence}"
    return hashlib.sha1(raw.encode()).hexdigest()


def normalized_track(src, args):
    """Normalise src once and cache it in build/normalized (re-done only when inputs change)."""
    dst = NORMALIZED_DIR / f"{src.stem}_{src.suffix.lstrip('.').lower()}.wav"
    meta = dst.with_suffix(".json")
    key = cache_key(src, args)
    if dst.exists() and meta.exists():
        cached = json.loads(meta.read_text())
        if cached.get("key") == key:
            return dst, cached
    print(f"  normalizing {src.name} ...")
    report = normalize(src, dst, args.target_lufs, args.true_peak, args.sample_rate, args.trim_silence)
    info = {"key": key, "output_lufs": report["output_i"], "output_tp": report["output_tp"],
            "mode": report.get("normalization_type", ""), "duration_sec": round(probe_duration(dst), 2)}
    meta.write_text(json.dumps(info, indent=2))
    return dst, info


def load_mapping(slots, tracks):
    """data/mapping.csv: columns slot,track - slot is a slot name or asset_path, track a file in tracks/."""
    if not MAPPING_CSV.exists():
        return {}
    by_name = defaultdict(list)
    for s in slots:
        by_name[s["name"]].append(s["asset_path"])
        by_name[s["asset_path"]].append(s["asset_path"])
    track_by_name = {t.name: t for t in tracks}
    mapping = {}
    for row in read_csv(MAPPING_CSV):
        slot, track = (row.get("slot") or "").strip(), (row.get("track") or "").strip()
        if not slot or slot.startswith("#"):
            continue
        if slot not in by_name:
            die(f"mapping.csv: unknown slot '{slot}'")
        if track not in track_by_name:
            die(f"mapping.csv: track '{track}' not found in tracks/")
        for path in by_name[slot]:
            mapping[path] = track_by_name[track]
    return mapping


def build(args):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        die("ffmpeg/ffprobe not found on PATH")
    slots = load_slots()
    tracks = sorted((p for p in TRACKS_DIR.iterdir() if p.suffix.lower() in AUDIO_EXTS),
                    key=lambda p: p.name.lower()) if TRACKS_DIR.is_dir() else []
    if not tracks:
        die(f"no audio files in {TRACKS_DIR.relative_to(REPO)}/ ({', '.join(sorted(AUDIO_EXTS))})")
    if args.order == "shuffle":
        random.Random(args.seed).shuffle(tracks)
    mapping = load_mapping(slots, tracks)

    # Assign a track to every slot: explicit mapping first, otherwise round-robin per set.
    assignment = {}
    for set_name in ("normal", "streamer"):
        set_slots = [s for s in slots if s["set"] == set_name]
        free = [s for s in set_slots if s["asset_path"] not in mapping]
        if len(tracks) > len(set_slots):
            print(f"warning: {len(tracks)} tracks but only {len(set_slots)} {set_name} slots - "
                  f"{len(tracks) - len(set_slots)} tracks will not play in that set")
        for i, s in enumerate(free):
            assignment[s["asset_path"]] = tracks[i % len(tracks)]
    assignment.update(mapping)

    print(f"normalizing to {args.target_lufs} LUFS / {args.true_peak} dBTP, {args.sample_rate} Hz")
    infos = {t: normalized_track(t, args) for t in sorted(set(assignment.values()))}

    if IMPORT_DIR.exists():
        shutil.rmtree(IMPORT_DIR)
    rows = []
    for s in slots:
        track = assignment[s["asset_path"]]
        norm, info = infos[track]
        wav = IMPORT_DIR / (s["asset_path"][len("/Game/"):] + ".wav")
        wav.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(norm, wav)
        rows.append({**{k: s.get(k, "") for k in WAVE_PROPS},
                     "asset_path": s["asset_path"], "wav": wav.relative_to(REPO).as_posix(),
                     "track": track.name, "set": s["set"], "duration_sec": info["duration_sec"],
                     "output_lufs": info["output_lufs"]})
    write_csv(MANIFEST_CSV, MANIFEST_FIELDS, rows)

    print()
    print(f"{'set':<9}{'slot':<58}{'track'}")
    for r in rows:
        print(f"{r['set']:<9}{r['asset_path'].rsplit('/', 1)[1][:56]:<58}{r['track']}")
    print()
    for track, (_, info) in infos.items():
        flag = "" if info["mode"] in ("", "linear") else \
            "  (loudnorm fell back to dynamic mode and compressed it; try a lower --target-lufs)"
        print(f"{info['output_lufs']:>7} LUFS {info['output_tp']:>6} dBTP {info['duration_sec']:7.1f}s  "
              f"{track.name}{flag}")
    print(f"\n{len(rows)} slots -> {IMPORT_DIR.relative_to(REPO)}/, manifest: {MANIFEST_CSV.relative_to(REPO)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="print loudness of audio files (e.g. vanilla jukebox exports)")
    m.add_argument("files", nargs="+", type=Path)
    b = sub.add_parser("build", help="normalise tracks and lay them out per jukebox slot")
    b.add_argument("--target-lufs", type=float, default=-11.0,
                   help="integrated loudness target; match the vanilla tracks (default -11: vanilla jukebox is about -12..-9)")
    b.add_argument("--true-peak", type=float, default=-1.0, help="true-peak ceiling in dBTP (default -1)")
    b.add_argument("--sample-rate", type=int, default=48000)
    b.add_argument("--trim-silence", action="store_true", help="cut leading/trailing silence")
    b.add_argument("--order", choices=["name", "shuffle"], default="name",
                   help="round-robin order of tracks (default: by file name)")
    b.add_argument("--seed", type=int, default=1, help="seed for --order shuffle")
    args = ap.parse_args()
    if args.cmd == "measure":
        measure(args.files)
    else:
        build(args)


if __name__ == "__main__":
    main()
