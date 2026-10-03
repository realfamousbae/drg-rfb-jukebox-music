# RFB Jukebox

Мод для **Deep Rock Galactic**: все песни джукбокса в баре Space Rig, включая набор стримерского режима, заменены на 39 треков Lida, CMH и компании.

- **Только звук.** В паке лежат одни SoundWave-ассеты, игровые блюпринты не тронуты.
- **На клиенте.** Музыку слышит только тот, у кого стоит мод. Остальным игрокам в лобби мод не нужен.
- **Каждый трек начинается с хука или дропа** и подогнан под время, которое игра отводит песне.

## Как это устроено

У песен джукбокса нет Sound Cue: `BP_JukeBox` проигрывает SoundWave из `Content/Audio/Music/JukeBox/**` напрямую. Мод собирает в UE 4.27 ассеты **с теми же путями и именами** и упаковывает их в `RFB_Jukebox_P.pak`.

| Набор | Слотов | Ванильная длительность | Особенности |
|---|---|---|---|
| `normal` | 39 | 1:01 – 4:20 | streaming |
| `streamer` (`TRJMusic`) | 8 | 0:51 – 2:36 | без streaming, `bLooping` |

Что выяснилось по ходу работы:

- **Игра проигрывает каждый слот ровно его ванильную длительность.** Она берёт её из своего `AssetRegistry.bin`, который мод заменить не может, а не из ассета. Длинный трек затухнет раньше, после короткого останется тишина. Поэтому каждый слот рендерится ровно на свою ванильную длину (`--fit-slots`). Длинные треки ставятся в длинные слоты, начало берётся из `data/cuts.csv`. Если трек короче слота больше чем на 10 с, он доигрывает повтором с дропа.
- **Громкость и затухание с расстоянием задаёт `BP_JukeBox`** (SoundClass `Music_JukeBox`, `GenericSoundAttenuation`). У самих SoundWave их нет, поэтому заглушки из EmptyContentHierarchy не нужны.
- **Ваниль звучит примерно на −12…−9 LUFS.** Треки выравниваются до −11 LUFS при потолке −1 dBTP, только линейным усилением, без компрессии. Трек, которому пики не дают дотянуть до цели, остаётся чуть тише.
- Ванильный множитель `Volume` (1.7 у одного слота) не переносится: он компенсировал тихий ванильный трек.

## Структура

```
data/
  playlist.tsv         треклист: исполнители, название, длительность, ссылка на YouTube, обрезка клипа
  cuts.csv             с какой секунды начинается каждый трек (хук/дроп)
  jukebox_slots.csv    слоты джукбокса и их ванильные свойства
  mapping.example.csv  образец data/mapping.csv: закрепить трек за слотом
modio/description.md   тексты и настройки страницы мода на mod.io
CHANGELOG.md           история версий
tools/
  fetch_tracks.py      скачивает треки из playlist.tsv в tracks/ (WAV 24 бит / 48 кГц)
  scan_slots.py        список слотов из пака игры (repak unpack) или из экспорта FModel
  prepare_tracks.py    громкость, срезы, раскладка по слотам → build/import/
  ue_import.py         импорт WAV в UE-проект как SoundWave с ванильными флагами
  collect_cooked.py    берёт из cook только ассеты слотов
  build.ps1            всё по порядку: подготовка → импорт → cook → пак → zip
tracks/                аудио, в git не хранится
```

## Сборка

Нужны Windows, **UE 4.27.2**, [Audio-Modding-Template](https://github.com/DRG-Modding/Audio-Modding-Template) (в `FSD.uproject` включены `PythonScriptPlugin` и `EditorScriptingUtilities`), [repak](https://github.com/trumank/repak), Python 3.8+ (только стандартная библиотека), ffmpeg, yt-dlp и deno. Путь к репозиторию без пробелов.

```
python tools/fetch_tracks.py
powershell -ExecutionPolicy Bypass -File tools\build.ps1 -Project <template>\FSD.uproject -Repak <repak.exe> -TrimSilence -Shuffle -Seed 1 -FitSlots
```

Результат: `dist\RFB_Jukebox_P.pak` и `dist\RFB_Jukebox.zip` для mod.io. Редактор UE при сборке должен быть закрыт. Путь к UE 4.27 скрипт находит сам через Epic Launcher, задать его вручную можно параметром `-UERoot`. Продолжить с середины можно флагами `-SkipPrepare`, `-SkipImport`, `-SkipCook`.

Для локального теста `.pak` удобно ставить через [mint](https://github.com/trumank/mint).

### Треки

- `fetch_tracks.py` скачивает лучшее аудио по ссылке из `playlist.tsv` и пропускает уже скачанное. Строка N становится файлом `tracks/NN Исполнители - Название.wav`.
- Для строки с пустым `url` скрипт ищет видео на YouTube по длительности. Посмотреть, что он выбрал, можно через `--dry-run`, перекачать один трек через `--force --only N`.
- Колонка `trim` (`START-END`, в секундах) обрезает клип до самой песни, например `-163`.
- В `cuts.csv` в колонке `start` указано, сколько секунд срезать в начале, чтобы трек стартовал с хука или дропа. Точки подобраны по громкости и басу и правятся вручную.
- `-Shuffle -Seed 1` даёт одинаковую раскладку на любой машине. В `data/mapping.csv` трек можно закрепить за конкретным слотом.

## После патча DRG

```
repak unpack -i FSD/Content/Audio/Music/JukeBox -o <dir> "<DRG>\FSD\Content\Paks\FSD-WindowsNoEditor.pak"
python tools/scan_slots.py <dir>\FSD\Content\Audio\Music\JukeBox
git diff data/jukebox_slots.csv
```

Если слоты и их длительности не изменились, мод пересобирать не нужно. Если изменились, пересобери и залей новую версию файла в тот же мод на mod.io.

---

Вся музыка принадлежит её исполнителям и лейблам. Мод скрытый и предназначен для друзей.
