#!/usr/bin/env python3
"""Copy ONLY the cooked jukebox SoundWaves into a folder ready for packing.

    python tools/collect_cooked.py --cooked "<FSD project>/Saved/Cooked/WindowsNoEditor" --clean
    python tools/collect_cooked.py --cooked "<Package Project output>/WindowsNoEditor" --layout drgpacker --clean

Keeping the pak to audio assets only is what lets the game auto-verify the mod,
so everything that is not a jukebox slot from build/import/manifest.csv is left out.

Layouts:
  repak      pak/RFB_Jukebox_P/FSD/Content/...  -> repak pack --version V11 pak/RFB_Jukebox_P
  drgpacker  pak/RFB_Jukebox_P/Content/...      -> drag the folder onto DRGPacker's _Repack.bat
"""
import argparse
import shutil
from pathlib import Path

from common import MANIFEST_CSV, REPO, die, read_csv

REQUIRED_EXTS = (".uasset", ".uexp")
OPTIONAL_EXTS = (".ubulk", ".uptnl")


def find_content_dir(cooked):
    for candidate in (cooked, cooked / "Content", cooked / "FSD" / "Content",
                      cooked / "WindowsNoEditor" / "FSD" / "Content"):
        if candidate.name == "Content" and candidate.is_dir():
            return candidate
    die(f"no cooked FSD/Content folder under {cooked}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cooked", type=Path, required=True,
                    help="cooked output: .../WindowsNoEditor, .../WindowsNoEditor/FSD or .../FSD/Content")
    ap.add_argument("--layout", choices=["repak", "drgpacker"], default="repak")
    ap.add_argument("--out", type=Path, default=REPO / "pak" / "RFB_Jukebox_P",
                    help="folder to fill; its name becomes the pak name, so keep the _P suffix")
    ap.add_argument("--clean", action="store_true", help="delete --out first")
    args = ap.parse_args()

    if not args.out.name.endswith("_P"):
        die(f"--out folder name must end with _P (the game ignores paks without it): {args.out.name}")
    if not MANIFEST_CSV.exists():
        die(f"{MANIFEST_CSV.relative_to(REPO)} not found - run tools/prepare_tracks.py build first")
    content = find_content_dir(args.cooked)

    dest_content = args.out / "FSD" / "Content" if args.layout == "repak" else args.out / "Content"

    rows = read_csv(MANIFEST_CSV)
    files, missing = [], []
    for row in rows:
        rel = row["asset_path"][len("/Game/"):]
        for ext in REQUIRED_EXTS + OPTIONAL_EXTS:
            src = content / (rel + ext)
            if src.exists():
                files.append((src, dest_content / (rel + ext)))
            elif ext in REQUIRED_EXTS:
                missing.append(src)
    if missing:
        die("cooked files missing (did the cook include these assets?):\n  " +
            "\n  ".join(str(m) for m in missing))

    if args.out.exists() and any(args.out.iterdir()):
        if not args.clean:
            die(f"{args.out} is not empty - pass --clean to rebuild it")
        shutil.rmtree(args.out)
    total = 0
    for src, dst in files:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        total += src.stat().st_size
    copied = len(files)

    sound_control = content / "Audio" / "SoundControl"
    if sound_control.is_dir() and any(sound_control.rglob("*.uasset")):
        print("warning: Audio/SoundControl was cooked - add it to 'Directories to never cook'. "
              "It is not copied into the pak, but the setting keeps cooks clean.")

    print(f"{len(rows)} SoundWaves, {copied} files, {total / 1024 / 1024:.1f} MiB -> {args.out}")
    if args.layout == "repak":
        print(f"next: repak pack --version V11 \"{args.out}\"")
    else:
        print(f"next: drag \"{args.out}\" onto DRGPacker's _Repack.bat")


if __name__ == "__main__":
    main()
