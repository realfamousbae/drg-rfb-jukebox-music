"""Import build/import/*.wav into the Audio-Modding-Template project as the vanilla jukebox SoundWaves.

Runs inside Unreal Editor 4.27 (embedded Python 3.7) with the "Python Editor Script Plugin" and
"Editor Scripting Utilities" plugins enabled. Either:
  - Editor: File > Execute Python Script... > tools/ue_import.py
  - Commandlet (editor closed):
      UE4Editor-Cmd.exe <path>/FSD.uproject -run=pythonscript -script=<repo>/tools/ue_import.py

Every WAV is imported under its exact vanilla path and name, then the SoundWave gets the vanilla
properties recorded by scan_slots.py (SoundClass, attenuation, looping, streaming; not volume).
SoundClass/attenuation assets are resolved from the template's dummy Audio/SoundControl folder,
which must be listed in "Directories to never cook" so the cooked waves point at the game's assets.
"""
import csv
import os

import unreal

DEFAULT_COMPRESSION_QUALITY = 80  # UE default is 40; music deserves more

try:
    REPO = os.environ.get("RFB_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    REPO = os.environ.get("RFB_REPO", "")
MANIFEST = os.path.join(REPO, "build", "import", "manifest.csv")


def log(msg):
    unreal.log("[rfb-jukebox] " + msg)


def warn(msg):
    unreal.log_warning("[rfb-jukebox] " + msg)


def as_bool(value):
    return str(value).strip().lower() in ("true", "1", "yes")


def load_ref(path, kind, consequence):
    if not path:
        return None
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        warn("{} {} not found in the project - copy Audio/SoundControl from the template/"
             "EmptyContentHierarchy, otherwise {}".format(kind, path, consequence))
        return None
    return unreal.EditorAssetLibrary.load_asset(path)


def set_prop(wave, name, value):
    try:
        wave.set_editor_property(name, value)
    except Exception as e:  # property names differ slightly between engine versions
        warn("{}: could not set {}: {}".format(wave.get_name(), name, e))


def apply_vanilla_props(wave, row):
    sound_class = load_ref(row.get("sound_class"), "SoundClass", "the in-game volume sliders may not apply")
    if sound_class:
        set_prop(wave, "sound_class_object", sound_class)
    attenuation = load_ref(row.get("attenuation"), "SoundAttenuation",
                           "the music will not fade with distance from the jukebox")
    if attenuation:
        set_prop(wave, "attenuation_settings", attenuation)
    # Vanilla "volume" is deliberately not copied: it compensated for quiet vanilla tracks (e.g. 1.7 on
    # Jukebox_Greek_*), while ours are already loudness-normalized by prepare_tracks.py.
    set_prop(wave, "compression_quality", int(row.get("compression_quality") or DEFAULT_COMPRESSION_QUALITY))
    set_prop(wave, "looping", as_bool(row.get("looping")))
    if row.get("streaming"):
        set_prop(wave, "streaming", as_bool(row["streaming"]))


def main():
    if not os.path.isfile(MANIFEST):
        raise RuntimeError("manifest not found: {} - run `python tools/prepare_tracks.py build` first "
                           "(or set RFB_REPO to the repo path)".format(MANIFEST))
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log("importing {} jukebox slots from {}".format(len(rows), MANIFEST))

    tasks = []
    for row in rows:
        wav = os.path.join(REPO, row["wav"])
        if not os.path.isfile(wav):
            raise RuntimeError("missing WAV: " + wav)
        package_dir, name = row["asset_path"].rsplit("/", 1)
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", wav)
        task.set_editor_property("destination_path", package_dir)
        task.set_editor_property("destination_name", name)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", False)
        tasks.append(task)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

    failed = []
    with unreal.ScopedSlowTask(len(rows), "Applying vanilla SoundWave settings") as slow:
        slow.make_dialog(True)
        for row in rows:
            slow.enter_progress_frame(1, row["asset_path"])
            wave = unreal.EditorAssetLibrary.load_asset(row["asset_path"])
            if not isinstance(wave, unreal.SoundWave):
                failed.append(row["asset_path"])
                continue
            apply_vanilla_props(wave, row)
            unreal.EditorAssetLibrary.save_loaded_asset(wave, False)

    if failed:
        raise RuntimeError("import failed for {} assets:\n  {}".format(len(failed), "\n  ".join(failed)))
    log("done: {} SoundWaves imported and saved".format(len(rows)))


main()
