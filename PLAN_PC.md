# План для сессии на Windows-ПК

Статус на 2026-10-01. Подробности каждого шага в [README.md](README.md), здесь только порядок, контекст и подводные камни.
По мере выполнения отмечай пункты `[x]` и коммить.

## Что уже сделано (на Mac)

- Тестовый плейлист Spotify, 26 треков (цель — 39, остальные добавятся позже), записан в `data/playlist.tsv`. У всех строк есть ссылка на YouTube.
- Пользователь прослушал и одобрил все 26 версий. **Не меняй ссылки без его согласия.** У официального видео №12 ограничение 18+, поэтому стоит ссылка с фан-канала, так задумано.
- `tools/fetch_tracks.py` скачивает аудио (`yt-dlp -f ba`) и конвертирует его в WAV 24 бит / 48 кГц в `tracks/`. WAV в git не лежат, на ПК их нужно скачать заново.

## 0. Окружение

- [ ] `git pull`
- [ ] Поставить: `winget install yt-dlp.yt-dlp DenoLand.Deno Gyan.FFmpeg` и Python 3.8+. Deno нужен для `--remote-components ejs:github`.
- [ ] Остальное по таблице в README §0: UE 4.27.2, FModel, Audio-Modding-Template, EmptyContentHierarchy, repak, mint.
- [ ] Репозиторий должен лежать в пути без пробелов, например `C:\Mods\drg-rfb-music`.

## 1. Треки

- [ ] `python tools/fetch_tracks.py`: должно получиться 26 файлов `tracks/NN ....wav`, исходники `.webm` в `tracks/_src/`.
- [ ] На Windows скрипт ещё не запускался. Если что-то сломается, чини сам скрипт. Возможные проблемы:
  - кириллица в выводе или в именах файлов: попробуй `set PYTHONUTF8=1`;
  - `yt-dlp` не находит `deno`;
  - для строк с заданным `url` поиск не выполняется, поэтому искажённые названия от поиска на скачивание не влияют.
- [ ] Проверить формат через `ffprobe`: 48000 Гц, 2 канала, 24 бит. Длительности должны совпадать с колонкой `duration` (±1 с).

## 2. Слоты джукбокса (FModel), README §1

- [ ] Экспортировать `FSD/Content/Audio/Music/JukeBox` в .json, затем `python tools/scan_slots.py "<FModel>\Output\Exports\FSD\Content\Audio\Music\JukeBox"`, затем закоммитить `data/jukebox_slots.csv`.
- [ ] Сообщить пользователю число слотов в наборах `normal` и `streamer`. Треков сейчас 26, цель 39: если слотов больше, треки пойдут по кругу, если меньше, лишние не войдут. Пусть решит сам.
- [ ] Выгрузить 1–2 ванильные песни и выполнить `python tools/prepare_tracks.py measure <файл>`. Полученный LUFS станет значением `--target-lufs`.
- [ ] Посмотреть блюпринт джукбокса: не выводит ли он названия песен и не зашиты ли где-то длительности.

## 3. Проект UE 4.27, README §3

- [ ] Скопировать `Content/Audio` из EmptyContentHierarchy в Audio-Modding-Template.
- [ ] Включить плагины Python Editor Script Plugin и Editor Scripting Utilities.
- [ ] Прописать в `DefaultGame.ini` `+DirectoriesToNeverCook=(Path="/Game/Audio/SoundControl")`. Это обязательно, иначе не пройдёт авто-верификация.

## 4. Сборка, README §4

- [ ] `powershell -ExecutionPolicy Bypass -File tools\build.ps1 -Project <путь>\FSD.uproject -TargetLufs <из шага 2> -TrimSilence`
- [ ] Результат: `dist\RFB_Jukebox_P.pak` и `dist\RFB_Jukebox.zip`. Имя пака обязательно заканчивается на `_P`.

## 5. Тест в игре, README §5

- [ ] Через mint (заодно прогнать линтер) или вручную через `FSD/Content/Paks`. При ручной установке игра переключается на песочный сейв, так что **после теста пак удалить**.
- [ ] Пройти чек-лист из README §5, streamer mode тоже проверить.

## 6. mod.io, README §6

- [ ] Мод скрытый (Hidden), загрузить zip, тег Audio, **без** категорий `[AimedFor...]`. Мод с одним аудио проходит верификацию автоматически.
- [ ] Друзей добавить в Team. Проверить заход в лобби с другом.
- [ ] Прежде чем публиковать или загружать что-то на mod.io, спросить пользователя.

## Контекст проекта

- Пользователь говорит по-русски. Разработка идёт на Mac (скрипты, подготовка треков), игра, UE, cook и тесты на этом ПК.
- Мод заменяет все слоты джукбокса в Space Rig, включая стримерский набор `TRJMusic`. Песни джукбокса — это SoundWave в `Content/Audio/Music/JukeBox` (+ `NewMusic`, `NewMusic_june2020`, `TRJMusic`). `Jukebox_Cue` — реплики гномов, не музыка.
- Гайд: https://drg-modding.github.io/docs/guides/audio-modding-guide.html
