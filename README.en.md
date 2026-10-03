# RFB Jukebox

[Русский](README.md) · **English**

A **Deep Rock Galactic** mod that replaces every song in the Space Rig bar jukebox, including the streamer-mode set, with 39 tracks by Lida, CMH and friends.

- **Audio only.** The pak contains nothing but SoundWave assets; game blueprints are untouched.
- **Client-side.** Only players who have the mod hear the music; nobody else in the lobby needs it.
- **Every track starts at its hook/drop** and is fitted to the time the game gives each song.

## How it works

Jukebox songs have no Sound Cue: `BP_JukeBox` plays the SoundWaves in `Content/Audio/Music/JukeBox/**` directly. The mod builds assets **with the same paths and names** in UE 4.27 and packs them into `RFB_Jukebox_P.pak`.

| Set | Slots | Vanilla length | Notes |
|---|---|---|---|
| `normal` | 39 | 1:01 – 4:20 | streamed |
| `streamer` (`TRJMusic`) | 8 | 0:51 – 2:36 | not streamed, `bLooping` |

Findings along the way:

- **The game plays each slot for exactly its vanilla duration.** It reads that value from its own `AssetRegistry.bin`, which a mod cannot replace, not from the asset. A longer track fades out early, a shorter one leaves silence. So every slot is rendered at exactly its vanilla length (`--fit-slots`): long tracks go to long slots, and playback starts at the point from `data/cuts.csv`. A track more than 10 s shorter than its slot keeps playing by repeating from the drop.
- **Volume and distance falloff come from `BP_JukeBox`** (SoundClass `Music_JukeBox`, `GenericSoundAttenuation`). The SoundWaves themselves have neither, so the EmptyContentHierarchy dummies aren't needed.
- **Vanilla songs sit at about −12…−9 LUFS.** Tracks are normalized to −11 LUFS with a −1 dBTP ceiling, using linear gain only, no compression. A track whose peaks don't allow reaching the target stays slightly quieter.
- The vanilla `Volume` multiplier (1.7 on one slot) is not copied: it only compensated for a quiet vanilla track.

## Layout

```
data/
  playlist.tsv         tracklist: artists, title, duration, YouTube link, music-video trim
  cuts.csv             the second each track starts at (hook/drop)
  jukebox_slots.csv    jukebox slots and their vanilla properties
  mapping.example.csv  sample data/mapping.csv: pin a track to a slot
modio/description.md   mod.io page texts and settings
CHANGELOG.md           version history
tools/
  fetch_tracks.py      downloads the playlist into tracks/ (WAV 24-bit / 48 kHz)
  scan_slots.py        lists slots from the game pak (repak unpack) or an FModel export
  prepare_tracks.py    loudness, cuts, slot layout → build/import/
  ue_import.py         imports the WAVs into the UE project as SoundWaves with vanilla flags
  collect_cooked.py    takes only the slot assets from the cook output
  build.ps1            everything in order: prepare → import → cook → pak → zip
tracks/                audio, not stored in git
```

## Building

Requires Windows, **UE 4.27.2**, [Audio-Modding-Template](https://github.com/DRG-Modding/Audio-Modding-Template) (with `PythonScriptPlugin` and `EditorScriptingUtilities` enabled in `FSD.uproject`), [repak](https://github.com/trumank/repak), Python 3.8+ (standard library only), ffmpeg, yt-dlp and deno. The repo path must not contain spaces.

```
python tools/fetch_tracks.py
powershell -ExecutionPolicy Bypass -File tools\build.ps1 -Project <template>\FSD.uproject -Repak <repak.exe> -TrimSilence -Shuffle -Seed 1 -FitSlots
```

Output: `dist\RFB_Jukebox_P.pak` and `dist\RFB_Jukebox.zip` for mod.io. The UE editor must be closed while building. The script finds UE 4.27 through the Epic Games Launcher; set the path manually with `-UERoot`. To resume midway, use `-SkipPrepare`, `-SkipImport` or `-SkipCook`.

For local testing, install the `.pak` with [mint](https://github.com/trumank/mint).

### Tracks

- `fetch_tracks.py` downloads the best audio from the link in `playlist.tsv` and skips what's already there. Row N becomes `tracks/NN Artists - Title.wav`.
- For a row with an empty `url`, the script searches YouTube by duration. Use `--dry-run` to see its pick and `--force --only N` to re-download a single track.
- The `trim` column (`START-END`, in seconds) cuts a music video down to the song, e.g. `-163`.
- In `cuts.csv`, `start` is the second the hook/drop begins. The points were picked from loudness and bass and can be edited by hand.
- `-Shuffle -Seed 1` gives the same layout on any machine. `data/mapping.csv` pins a track to a specific slot.

## After a DRG patch

```
repak unpack -i FSD/Content/Audio/Music/JukeBox -o <dir> "<DRG>\FSD\Content\Paks\FSD-WindowsNoEditor.pak"
python tools/scan_slots.py <dir>\FSD\Content\Audio\Music\JukeBox
git diff data/jukebox_slots.csv
```

If the slots and their durations haven't changed, there's no need to rebuild. If they have, rebuild and upload the new file to the same mod on mod.io.

---

All music belongs to its artists and labels. The mod is hidden and meant for friends.
