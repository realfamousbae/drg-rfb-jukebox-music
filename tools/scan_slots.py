#!/usr/bin/env python3
"""Build data/jukebox_slots.csv from an FModel export of the jukebox music folder.

In FModel: right-click Content/Audio/Music/JukeBox -> "Save Folder's Packages Properties (.json)".
Then point this script at FModel's Output/Exports directory (or any folder inside it):

    python tools/scan_slots.py "C:/FModel/Output/Exports/FSD/Content/Audio/Music/JukeBox"

Raw cooked .uasset/.uexp files also work, e.g. unpacked straight from the game pak with repak:

    repak unpack -i FSD/Content/Audio/Music/JukeBox -o <dir> FSD-WindowsNoEditor.pak
    python tools/scan_slots.py <dir>/FSD/Content/Audio/Music/JukeBox

That reads Duration, Volume, bLooping and bStreaming, but cannot resolve SoundClass/Attenuation
references (vanilla jukebox waves have none as of build 25433570).
"""
import argparse
import json
import re
import struct
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


def uasset_names(data):
    """Name map of a cooked UE4 (4.27, unversioned custom versions) package summary."""
    o = 4
    legacy = struct.unpack_from("<i", data, o)[0]
    o += 4 if legacy == -4 else 8
    o += 8  # FileVersionUE4, FileVersionLicenseeUE4
    o += 4 + struct.unpack_from("<i", data, o)[0] * 20  # custom versions
    o += 4  # TotalHeaderSize
    n = struct.unpack_from("<i", data, o)[0]
    o += 4 + (n if n >= 0 else -2 * n)  # FolderName
    o += 4  # PackageFlags
    count, offset = struct.unpack_from("<ii", data, o)
    names, o = [], offset
    for _ in range(count):
        n = struct.unpack_from("<i", data, o)[0]
        o += 4
        if n < 0:
            names.append(data[o:o - 2 * n - 2].decode("utf-16-le"))
            o += -2 * n
        else:
            names.append(data[o:o + n - 1].decode("latin-1"))
            o += n
        o += 4  # hash
    return names


def slot_from_uasset(file):
    """Read the few tagged SoundWave properties straight from a raw .uasset/.uexp pair (e.g. a repak unpack).

    Tagged properties that equal the class default are not serialized, so a missing bool means false."""
    try:
        names = uasset_names(file.read_bytes())
        uexp = file.with_suffix(".uexp").read_bytes()
    except (OSError, struct.error, UnicodeDecodeError) as e:
        print(f"  skip {file.name}: {e}")
        return None
    if "SoundWave" not in names:
        return None

    def tag(prop, typ, size):
        if prop not in names or typ not in names:
            return -1, b""
        pat = struct.pack("<iiiiii", names.index(prop), 0, names.index(typ), 0, size, 0)
        return uexp.find(pat), pat

    def float_prop(prop):
        i, pat = tag(prop, "FloatProperty", 4)
        return struct.unpack_from("<f", uexp, i + len(pat) + 1)[0] if i >= 0 else None  # +1: HasPropertyGuid

    def bool_prop(prop):
        i, pat = tag(prop, "BoolProperty", 0)
        return "true" if i >= 0 and uexp[i + len(pat)] else "false"

    duration, volume = float_prop("Duration"), float_prop("Volume")
    if "SoundClassObject" in names or "AttenuationSettings" in names:
        print(f"  note {file.name}: has SoundClass/Attenuation - raw scan can't resolve them, use an FModel .json export")
    return {
        "name": file.stem,
        "duration_sec": f"{duration:.2f}" if duration is not None else "",
        "sound_class": "",
        "attenuation": "",
        "volume": f"{volume:g}" if volume is not None else "",
        "compression_quality": "",
        "looping": bool_prop("bLooping"),
        "streaming": bool_prop("bStreaming"),
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
            info = slot_from_uasset(file)
            if info is None:
                continue
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
