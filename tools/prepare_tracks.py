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

from common import (CUTS_CSV, IMPORT_DIR, MANIFEST_CSV, MAPPING_CSV, REPO, BUILD, WAVE_PROPS, die, load_slots,
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


def normalize(src, dst, target_lufs, true_peak, sample_rate, trim, start=0.0):
    """Two-pass EBU R128 loudnorm; returns the loudnorm report of the second pass.

    start > 0 drops the first `start` seconds (data/cuts.csv) with a short fade-in.
    Always linear gain: if reaching target_lufs would push the true peak over true_peak, the track is
    raised only as far as its peak allows (ends up a bit quieter) instead of letting loudnorm fall back
    to dynamic mode, which compresses/pumps music."""
    pre = f"atrim=start={start},asetpts=PTS-STARTPTS,afade=t=in:d=0.3," if start else ""
    pre += TRIM_FILTER + "," if trim else ""
    first = last_json(run_ffmpeg(["-i", str(src), "-af",
                                  f"{pre}loudnorm=I={target_lufs}:TP={true_peak}:LRA=20:print_format=json",
                                  "-f", "null", "-"]))
    max_linear = float(first["input_i"]) + true_peak - float(first["input_tp"]) - 0.1
    target = f"I={min(target_lufs, round(max_linear, 1))}:TP={true_peak}:LRA=20"
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


def cache_key(src, args, start):
    st = src.stat()
    raw = f"{src.name}|{st.st_size}|{st.st_mtime_ns}|{args.target_lufs}|{args.true_peak}|" \
          f"{args.sample_rate}|{args.trim_silence}|linear-only|start={start}"
    return hashlib.sha1(raw.encode()).hexdigest()


def load_cuts(tracks):
    """data/cuts.csv: columns track,start[,note] - track is the NN number prefix or a file name in tracks/;
    start = where the hook/drop begins; with --fit-slots playback starts there (or earlier if the slot is long
    enough), since the game stops each slot at its vanilla duration."""
    if not CUTS_CSV.exists():
        return {}
    by_key = {t.name: t for t in tracks}
    for t in tracks:
        num = t.name.split(" ", 1)[0]
        if num.isdigit():
            by_key[str(int(num))] = t
    cuts = {}
    for row in read_csv(CUTS_CSV):
        key, start = (row.get("track") or "").strip(), (row.get("start") or "").strip()
        if not key or key.startswith("#") or not start:
            continue
        track = by_key.get(key) or by_key.get(key.lstrip("0"))
        if track is None:
            die(f"cuts.csv: track '{key}' not found in tracks/")
        cuts[track] = float(start)
    return cuts


def normalized_track(src, args, start=0.0):
    """Normalise src once and cache it in build/normalized (re-done only when inputs change)."""
    dst = NORMALIZED_DIR / f"{src.stem}_{src.suffix.lstrip('.').lower()}.wav"
    meta = dst.with_suffix(".json")
    key = cache_key(src, args, start)
    if dst.exists() and meta.exists():
        cached = json.loads(meta.read_text())
        if cached.get("key") == key:
            return dst, cached
    print(f"  normalizing {src.name}" + (f" from {start:g}s" if start else "") + " ...")
    report = normalize(src, dst, args.target_lufs, args.true_peak, args.sample_rate, args.trim_silence, start)
    info = {"key": key, "output_lufs": report["output_i"], "output_tp": report["output_tp"],
            "mode": report.get("normalization_type", ""), "duration_sec": round(probe_duration(dst), 2),
            "start": start}
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


FADE_OUT = 2.5
LOOP_XFADE = 1.5
MAX_TAIL_GAP = 10.0  # up to this many seconds short of the slot: end naturally + silence instead of looping


def fit_to_slot(src, dst, total, cut, slot_dur, sample_rate):
    """Render exactly slot_dur seconds of a normalized track for one slot.

    The game ends each jukebox song after its *vanilla* duration (read from the game's AssetRegistry,
    which a mod pak cannot replace), so every replacement must be exactly that long: start at the
    hook/drop (cut) - or earlier if the slot is long enough to afford it - and fade out at the end.
    A track shorter than the slot keeps playing by repeating from the drop (crossfaded) instead of
    leaving silence. Returns (start, looped)."""
    start = min(cut, max(0.0, total - slot_dur))
    remaining = total - start
    fade_in = ",afade=t=in:d=0.3" if start > 0 else ""
    if 0 < slot_dur - remaining <= MAX_TAIL_GAP:
        # a few seconds short: let the song end naturally, pad the rest with silence (no fade, no loop)
        graph = (f"[0:a]atrim=start={start},asetpts=PTS-STARTPTS{fade_in},apad=whole_dur={slot_dur},"
                 f"atrim=duration={slot_dur}[out]")
        dst.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(["-y", "-i", str(src), "-filter_complex", graph, "-map", "[out]",
                    "-ar", str(sample_rate), "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
        return start, False
    if remaining >= slot_dur:
        graph = f"[0:a]atrim=start={start},asetpts=PTS-STARTPTS[x]"
        looped = False
    else:
        loop_len = total - cut - LOOP_XFADE
        n = 1 + max(1, int((slot_dur - remaining) // max(loop_len, 1.0)) + 1)
        parts = [f"[0:a]asplit={n}" + "".join(f"[s{i}]" for i in range(n))]
        parts.append(f"[s0]atrim=start={start},asetpts=PTS-STARTPTS[c0]")
        for i in range(1, n):
            parts.append(f"[s{i}]atrim=start={cut},asetpts=PTS-STARTPTS[r{i}]")
            parts.append(f"[c{i - 1}][r{i}]acrossfade=d={LOOP_XFADE}[c{i}]")
        parts.append(f"[c{n - 1}]anull[x]")
        graph = ";".join(parts)
        looped = True
    graph += (f";[x]atrim=duration={slot_dur},asetpts=PTS-STARTPTS{fade_in},"
              f"afade=t=out:st={max(0.0, slot_dur - FADE_OUT):.3f}:d={FADE_OUT}[out]")
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-y", "-i", str(src), "-filter_complex", graph, "-map", "[out]",
                "-ar", str(sample_rate), "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
    return start, looped


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
        if args.fit_slots and set_name == "normal":
            # longest tracks into the longest slots, so trimming/looping is minimal
            pool = sorted(tracks[:len(free)], key=lambda t: probe_duration(t), reverse=True)
            for s, t in zip(sorted(free, key=lambda s: float(s["duration_sec"]), reverse=True), pool):
                assignment[s["asset_path"]] = t
            for i, s in enumerate(free[len(pool):]):
                assignment[s["asset_path"]] = tracks[i % len(tracks)]
            continue
        for i, s in enumerate(free):
            assignment[s["asset_path"]] = tracks[i % len(tracks)]
    assignment.update(mapping)

    print(f"normalizing to {args.target_lufs} LUFS / {args.true_peak} dBTP, {args.sample_rate} Hz")
    cuts = load_cuts(tracks)
    # with --fit-slots the cut is applied per slot (fit_to_slot), so normalize whole tracks
    infos = {t: normalized_track(t, args, 0.0 if args.fit_slots else cuts.get(t, 0.0))
             for t in sorted(set(assignment.values()))}

    if IMPORT_DIR.exists():
        shutil.rmtree(IMPORT_DIR)
    rows, notes = [], {}
    for s in slots:
        track = assignment[s["asset_path"]]
        norm, info = infos[track]
        wav = IMPORT_DIR / (s["asset_path"][len("/Game/"):] + ".wav")
        wav.parent.mkdir(parents=True, exist_ok=True)
        duration = info["duration_sec"]
        if args.fit_slots and s.get("duration_sec"):
            duration = float(s["duration_sec"])
            start, looped = fit_to_slot(norm, wav, info["duration_sec"], cuts.get(track, 0.0), duration,
                                        args.sample_rate)
            notes[s["asset_path"]] = f"{start:5.0f}s+{'loop' if looped else ''}"
        else:
            shutil.copyfile(norm, wav)
        rows.append({**{k: s.get(k, "") for k in WAVE_PROPS},
                     "asset_path": s["asset_path"], "wav": wav.relative_to(REPO).as_posix(),
                     "track": track.name, "set": s["set"], "duration_sec": round(duration, 2),
                     "output_lufs": info["output_lufs"]})
    write_csv(MANIFEST_CSV, MANIFEST_FIELDS, rows)

    print()
    print(f"{'set':<9}{'slot':<44}{'len':>7} {'from':<11}{'track'}")
    for r in rows:
        print(f"{r['set']:<9}{r['asset_path'].rsplit('/', 1)[1][:42]:<44}{r['duration_sec']:>6.0f}s "
              f"{notes.get(r['asset_path'], ''):<11}{r['track']}")
    print()
    for track, (_, info) in infos.items():
        quieter = args.target_lufs - float(info["output_lufs"])
        if info["mode"] not in ("", "linear"):
            flag = "  (loudnorm fell back to dynamic mode and compressed it)"
        elif quieter > 0.3:
            flag = f"  ({quieter:.1f} dB below target: peaks leave no more headroom)"
        else:
            flag = ""
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
    b.add_argument("--fit-slots", action="store_true",
                   help="render every slot at exactly its vanilla duration (the game cuts songs there): "
                        "long tracks to long slots, start at the cut from data/cuts.csv, fade out at the end")
    args = ap.parse_args()
    if args.cmd == "measure":
        measure(args.files)
    else:
        build(args)


if __name__ == "__main__":
    main()
