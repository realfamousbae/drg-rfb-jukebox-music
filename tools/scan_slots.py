#!/usr/bin/env python3
"""Build data/jukebox_slots.csv from an FModel export of the jukebox music folder.

In FModel: right-click Content/Audio/Music/JukeBox -> "Save Folder's Packages Properties (.json)".
Then point this script at FModel's Output/Exports directory (or any folder inside it):

    python tools/scan_slots.py "C:/FModel/Output/Exports/FSD/Content/Audio/Music/JukeBox"

Raw .uasset exports also work, but then only names are known (no duration or SoundClass).
"""
import argparse
import json
import re
from pathlib import Path

from common import REPO, SLOTS_CSV, SLOT_FIELDS, die, slot_set, write_csv


def game_path(file):
    """.../FSD/Content/Audio/Music/JukeBox/Foo.json -> /Game/Audio/Music/JukeBox/Foo"""
    parts = list(file.with_suffix("").parts)
    if "Content" not in parts:
        return None
    idx = len(parts) - 1 - parts[::-1].index("Content")
    return "/Game/" + "/".join(parts[idx + 1:])


def ref_to_game_path(ref):
    """Normalise an FModel object reference to a /Game/... package path ('' if none)."""
    if not ref:
        return ""
    if isinstance(ref, dict):
        p = ref.get("ObjectPath") or ref.get("AssetPathName") or ""
    else:
        p = str(ref)
    m = re.search(r"'([^']+)'", p)  # SoundClass'/Game/Audio/...'
    if m:
        p = m.group(1)
    p = re.sub(r"\.\d+$", "", p)  # FModel appends the export index: Foo.0
    if p.startswith("FSD/Content/"):
        p = "/Game/" + p[len("FSD/Content/"):]
    head, _, tail = p.rpartition("/")
    if "." in tail:  # /Game/Dir/Pkg.Obj -> /Game/Dir/Pkg
        p = head + "/" + tail.split(".", 1)[0]
    return p if p.startswith("/Game/") else ""


def slot_from_json(file):
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        print(f"  skip {file.name}: {e}")
        return None
    exports = data if isinstance(data, list) else [data]
    wave = next((e for e in exports if isinstance(e, dict) and e.get("Type") == "SoundWave"), None)
    if wave is None:
        return None
    props = wave.get("Properties") or {}
    duration = props.get("Duration", wave.get("Duration"))
    return {
        "name": wave.get("Name") or file.stem,
        "duration_sec": f"{float(duration):.2f}" if duration is not None else "",
        "sound_class": ref_to_game_path(props.get("SoundClassObject")),
        "attenuation": ref_to_game_path(props.get("AttenuationSettings")),
        "volume": props.get("Volume", ""),
        "compression_quality": props.get("CompressionQuality", ""),
        "looping": str(props.get("bLooping", "")).lower(),
        "streaming": str(props.get("bStreaming", "")).lower(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", type=Path, help="FModel export folder (.json or .uasset files)")
    ap.add_argument("--min-duration", type=float, default=30.0,
                    help="skip SoundWaves shorter than this many seconds, e.g. voice lines (default 30)")
    ap.add_argument("--out", type=Path, default=SLOTS_CSV)
    args = ap.parse_args()

    if not args.export.is_dir():
        die(f"not a directory: {args.export}")

    slots, skipped = {}, []
    for file in sorted(args.export.rglob("*")):
        if file.suffix.lower() not in (".json", ".uasset"):
            continue
        path = game_path(file)
        if path is None:
            die(f"{file} is not under a Content folder - export with FModel's default folder layout")
        if file.suffix.lower() == ".json":
            info = slot_from_json(file)
            if info is None:
                continue
        elif path in slots:  # the .json for this asset already gave us more detail
            continue
        else:
            info = {"name": file.stem}
        dur = info.get("duration_sec")
        if dur and float(dur) < args.min_duration:
            skipped.append(f"{path} ({dur}s)")
            continue
        slots[path] = {"asset_path": path, "set": slot_set(path), **info}

    if not slots:
        die("no SoundWave assets found - did you export the JukeBox folder's properties as .json?")

    rows = sorted(slots.values(), key=lambda s: (s["set"], s["asset_path"].lower()))
    write_csv(args.out, SLOT_FIELDS, rows)

    for set_name in ("normal", "streamer"):
        n = sum(1 for r in rows if r["set"] == set_name)
        print(f"{set_name:>8}: {n} slots")
    if skipped:
        print(f"skipped {len(skipped)} short SoundWaves (< {args.min_duration:g}s):")
        for s in skipped:
            print(f"  {s}")
    missing_class = [r["asset_path"] for r in rows if not r.get("sound_class")]
    if missing_class:
        print(f"note: {len(missing_class)} slots have no SoundClass in the export "
              f"(fine if vanilla has none; check one in FModel)")
    try:
        shown = args.out.resolve().relative_to(REPO)
    except ValueError:
        shown = args.out
    print(f"wrote {shown}")


if __name__ == "__main__":
    main()
