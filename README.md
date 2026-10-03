# RFB Jukebox — свои треки в джукбоксе Deep Rock Galactic

Мод заменяет все песни джукбокса в баре Space Rig, включая набор для стримерского режима (`TRJMusic`), на треки из папки `tracks/`. В пак попадают только аудиоассеты, поэтому игра сама помечает мод как **Verified**: прогресс и обычные лобби не затрагиваются.

Как это работает: у песен джукбокса нет Sound Cue, игра проигрывает SoundWave-ассеты из `Content/Audio/Music/JukeBox/**` напрямую. Мы готовим в UE 4.27 ассеты **с теми же именами и путями**, собираем из них `RFB_Jukebox_P.pak` и загружаем на mod.io.

- **Mac** — подготовка треков (`tools/prepare_tracks.py`) и правки скриптов.
- **Windows-ПК** — разведка через FModel, UE 4.27, cook, пак, тест в игре. Официальный UE 4.27 на macOS не умеет делать cook под Windows.

```
tracks/                 твои треки (mp3/flac/wav/ogg/m4a/…), в git не попадают
data/playlist.tsv       список треков: исполнители, название, длительность, ссылка на YouTube
data/jukebox_slots.csv  слоты джукбокса: генерирует tools/scan_slots.py
data/mapping.csv        (опц.) закрепить трек за слотом, образец: mapping.example.csv
tools/                  fetch_tracks скачивает треки; scan_slots → prepare_tracks → ue_import → collect_cooked, build.ps1 делает всё разом
modio/                  черновик страницы мода и лого
```

## 0. Установка на Windows-ПК (один раз)

| Что | Где взять | Зачем |
|---|---|---|
| Unreal Engine **4.27.2** | Epic Games Launcher (показывается как 4.27) | импорт и cook |
| FModel | https://github.com/iAmAsval/FModel | посмотреть и выгрузить ассеты игры |
| Audio-Modding-Template, ветка `main` | https://github.com/DRG-Modding/Audio-Modding-Template | UE-проект `FSD.uproject` |
| EmptyContentHierarchy (последняя) | https://github.com/DRG-Modding/tools | структура папок игры с dummy-ассетами `Audio/SoundControl` |
| repak | https://github.com/trumank/repak/releases | упаковка в `.pak` (или DRGPacker из того же `DRG-Modding/tools`) |
| Python 3.8+ и ffmpeg | python.org, `winget install ffmpeg` | скрипты |
| yt-dlp и deno | `winget install yt-dlp.yt-dlp DenoLand.Deno` | скачивание треков (`fetch_tracks.py`) |
| mint | https://github.com/trumank/mint | локальный тест и линтер пака |

Репозиторий положи в путь **без пробелов**, например `C:\Mods\drg-rfb-music`.

## 1. Какие слоты есть в игре (FModel, ПК)

**Быстрый путь без FModel** (repak):
```
repak unpack -i FSD/Content/Audio/Music/JukeBox -o X:\DRGModding\vanilla "<DRG>\FSD\Content\Paks\FSD-WindowsNoEditor.pak"
python tools/scan_slots.py X:\DRGModding\vanilla\FSD\Content\Audio\Music\JukeBox
```
Скрипт сам читает из ассетов `Duration`, `Volume`, `bLooping` и `bStreaming`. На билде 25433570 получилось 39 обычных слотов и 8 стримерских. SoundClass и Attenuation у ванильных песен не заданы. FModel по-прежнему нужен для п. 4–5.

Через FModel:
1. FModel → Directory → Selector → папка DRG → загрузить `FSD-WindowsNoEditor.pak`.
2. Правый клик по `FSD/Content/Audio/Music/JukeBox` → **Save Folder's Packages Properties (.json)**.
3. Собрать список слотов:
   ```
   python tools/scan_slots.py "<FModel>\Output\Exports\FSD\Content\Audio\Music\JukeBox"
   ```
   Скрипт запишет `data/jukebox_slots.csv`: путь, имя, набор (`normal` или `streamer`), длительность, а также ванильные SoundClass, Attenuation, Volume, CompressionQuality, Looping и Streaming. SoundWave короче 30 с (реплики гномов) он пропускает и выводит их список. `Jukebox_Cue` — это реплики, не музыка. Закоммить CSV.
4. Выгрузить 1–2 ванильные песни (правый клик → Export Raw Data / Save Audio) и замерить их громкость:
   ```
   python tools/prepare_tracks.py measure path\to\vanilla.ogg
   ```
   Полученное значение LUFS подставь в `--target-lufs` на следующем шаге, чтобы твои треки звучали так же громко, как ванильные. На билде 25433570 ванильные песни звучат примерно на −12…−9 LUFS, отсюда значение по умолчанию −11.
5. Заодно посмотри блюпринт джукбокса: не выводит ли он названия песен и не зашиты ли где-то длительности. Названия и жанры в UI останутся ванильными: их правка — уже не аудио, и авто-верификация слетит.

## 2. Подготовка треков (Mac или ПК)

Треки скачиваются по списку `data/playlist.tsv`: с YouTube берётся лучшее аудио, оно конвертируется в WAV 24 бит / 48 кГц.
```
python tools/fetch_tracks.py
```
Уже скачанные треки пропускаются. Исходники складываются в `tracks/_src/`. Строка N списка превращается в файл `NN Исполнители - Название.wav`.

Как добавить трек: допиши строку в `playlist.tsv`, колонку `url` оставь пустой. `python tools/fetch_tracks.py --dry-run` найдёт видео, совпадающее по длительности со Spotify. Проверь его и впиши ссылку в `url`, тогда на всех машинах скачается одна и та же версия. Если ничего подходящего нет или видео с ограничением 18+, возьми ссылку вручную. Перекачать один трек: `--force --only N`.

Можно и просто положить свои треки в `tracks/`. Порядок раскладки определяется именем файла, так что удобно добавлять префиксы `01 `, `02 ` и т.д.

```
python tools/prepare_tracks.py build --target-lufs -11 --trim-silence --order shuffle --seed 1
```
- Каждый трек один раз конвертируется в WAV 48 кГц / 16 бит / стерео. Громкость выравнивается двухпроходным `loudnorm` до цели с потолком true peak −1 dBTP. Результат кэшируется в `build/normalized/`.
- Обычный и стримерский наборы **независимо** проходят по всем трекам по кругу. Если треков меньше, чем слотов, они повторяются. Если больше, лишние не попадут в набор, и скрипт об этом предупредит.
- Джукбокс в игре примерно через 30–50 с плавно глушит песню. Поэтому `data/cuts.csv` (`track,start`: номер трека и сколько секунд отрезать от начала) сдвигает каждый трек так, чтобы хук или дроп звучал в первые секунды. Точки подобраны автоматически по громкости и басу, их можно править руками. Исходные WAV при этом не меняются.
- Закрепить трек за конкретным слотом можно через `data/mapping.csv`. Опции `--order shuffle --seed N` перемешивают треки. Для мода выбрано перемешивание с `--seed 1`: при том же seed и том же наборе треков раскладка одинакова на любой машине.
- Результат: `build/import/Audio/Music/JukeBox/**/<Слот>.wav` и `build/import/manifest.csv`. В конце печатается таблица «слот → трек» и LUFS каждого трека.

## 3. Проект UE 4.27 (ПК, один раз)

1. Открыть `FSD.uproject` из Audio-Modding-Template.
2. ~~Скопировать в него `Content/Audio` из EmptyContentHierarchy.~~ Для джукбокса это не нужно. Ванильные песни не ссылаются на SoundClass и Attenuation (их задаёт `BP_JukeBox`), а `Audio/SoundControl` в шаблоне уже есть.
3. Edit → Plugins: включить **Python Editor Script Plugin** и **Editor Scripting Utilities**, перезапустить редактор. Можно вместо этого вписать их в `FSD.uproject` в блок `"Plugins"`: `PythonScriptPlugin` и `EditorScriptingUtilities`, `"Enabled": true`.
4. Project Settings → Packaging (или сразу вписать в `Config/DefaultGame.ini`):
   ```ini
   [/Script/UnrealEd.ProjectPackagingSettings]
   UsePakFile=False
   bShareMaterialShaderCode=False
   +DirectoriesToNeverCook=(Path="/Game/Audio/SoundControl")
   ```
   `SoundControl` нельзя готовить: тогда ссылки в наших ассетах укажут на настоящие звуковые классы игры, а пустышки не попадут в пак.

## 4. Импорт → cook → пак

**Одной командой** (редактор UE закрыт):
```
powershell -ExecutionPolicy Bypass -File tools\build.ps1 -Project X:\DRGModding\Audio-Modding-Template\FSD.uproject -Repak X:\DRGModding\tools\repak\repak.exe -TrimSilence -Shuffle -Seed 1
```
UE 4.27 скрипт сам находит через манифесты Epic Launcher. Путь к нему можно задать явно через `-UERoot`. `-TargetLufs` по умолчанию −11.
Скрипт по очереди делает `prepare_tracks` → `ue_import.py` (headless) → `RunUAT BuildCookRun` → `collect_cooked` → `repak pack --version V11` → zip. На выходе `dist\RFB_Jukebox_P.pak` и `dist\RFB_Jukebox.zip`. Флаги `-SkipPrepare`, `-SkipImport`, `-SkipCook` позволяют продолжить с нужного шага.

**Вручную** (если автоматический cook капризничает):
1. В редакторе: File → Execute Python Script → `tools/ue_import.py`. Прослушай пару ассетов в `Content/Audio/Music/JukeBox`.
2. File → Package Project → Windows (64-bit) → выбрать папку.
3. Собрать папку для пака:
   ```
   python tools/collect_cooked.py --cooked "<папка>\WindowsNoEditor" --clean
   repak pack --version V11 pak\RFB_Jukebox_P dist\RFB_Jukebox_P.pak
   ```
   С DRGPacker: добавь `--layout drgpacker` и перетащи `pak\RFB_Jukebox_P` на `_Repack.bat`.

`collect_cooked.py` копирует **только** `.uasset/.uexp/.ubulk` слотов из манифеста. Если чего-то не хватает, он падает с ошибкой, а `AssetRegistry.bin`, шейдеры и прочее в пак не попадают. Имя пака обязательно заканчивается на `_P`.

## 5. Тест в игре

- **Через mint** (удобнее): добавить `dist\RFB_Jukebox_P.pak` как локальный мод → Install → запустить DRG. Заодно прогнать линтер mint: предупреждений быть не должно.
- **Вручную**: положить пак в `...\steamapps\common\Deep Rock Galactic\FSD\Content\Paks`. Мод будет помечен как DEPRECIATED, а игра включит песочный сейв. Это только для теста, **после теста пак удали**.

Чек-лист в баре Space Rig:
- [ ] джукбокс несколько раз подряд играет только твои треки, без тишины, треска и обрывов;
- [ ] трек доигрывает до конца, дальше включается следующий;
- [ ] ползунок громкости музыки влияет на джукбокс, звук затихает при удалении (как у ванили);
- [ ] со streamer mode в настройках тоже играют твои треки.

Типичные проблемы: тишина — не совпало имя или путь слота (регистр важен). Треск или «перегруз» — снизь `--target-lufs` на 2–3 dB. Громкость не регулируется — в проекте нет нужного SoundClass (смотри предупреждения `ue_import.py`).

## 6. mod.io (скрытый мод)

1. drg.mod.io → «+» → заполнить поля по `modio/description.md`, видимость **Hidden**.
2. Загрузить `dist\RFB_Jukebox.zip`.
3. Тег Audio. **Не ставить** `[AimedForVerified/Approved/Sandbox]`: аудио-мод верифицируется автоматически.
4. Друзей добавить в Team мода, иначе скрытый мод им не виден. Другой вариант — они ставят `.pak` через mint.
5. В игре: Modding → включить мод → проверить статус **Verified** и основной (не песочный) сейв.
6. Проверить с другом заход в лобби в обе стороны. Есть сообщения, что скрытые моды мешают входу. Если это подтвердится, сделай мод публичным (музыка твоя) или раздавай пак через mint.

## После патчей DRG

Повтори шаг 1 и сравни новый `data/jukebox_slots.csv` с закоммиченным (`git diff`). Если слоты не изменились, пересобирать не нужно. Если изменились — прогони шаги 2–4 и загрузи новый файл в тот же мод на mod.io.
