"""Shared helpers for the RFB Jukebox tooling (plain Python 3.8+, no dependencies)."""
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
BUILD = REPO / "build"

SLOTS_CSV = DATA / "jukebox_slots.csv"
MAPPING_CSV = DATA / "mapping.csv"
CUTS_CSV = DATA / "cuts.csv"
IMPORT_DIR = BUILD / "import"
MANIFEST_CSV = IMPORT_DIR / "manifest.csv"

# Properties copied from the vanilla SoundWave so the replacement behaves the same in game.
WAVE_PROPS = ["sound_class", "attenuation", "volume", "compression_quality", "looping", "streaming"]
SLOT_FIELDS = ["asset_path", "name", "set", "duration_sec"] + WAVE_PROPS

STREAMER_FOLDER = "TRJMusic"


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def slot_set(asset_path):
    """'streamer' for the streamer-mode (no-copyright) folder, 'normal' otherwise."""
    return "streamer" if STREAMER_FOLDER.lower() in asset_path.lower().split("/") else "normal"


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def load_slots():
    if not SLOTS_CSV.exists():
        die(f"{SLOTS_CSV.relative_to(REPO)} not found - run tools/scan_slots.py on an FModel export first")
    slots = read_csv(SLOTS_CSV)
    if not slots:
        die(f"{SLOTS_CSV.relative_to(REPO)} is empty")
    names = [s["asset_path"] for s in slots]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        die(f"duplicate slots in {SLOTS_CSV.name}: {', '.join(sorted(dupes))}")
    for s in slots:
        if not s["asset_path"].startswith("/Game/"):
            die(f"slot asset_path must start with /Game/: {s['asset_path']}")
    return slots
