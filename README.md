# Levita Display

Замена штатной Thermalright TRCC для **Levita Vision 360**: проигрывает GIF и MP4
из локальной папки на экране помпы, а цвет ARGB-вентиляторов подстраивает под
палитру текущего кадра.

Мониторинга и поиска GIF в интернете нет: только воспроизведение файлов из
`gifs/` (подпапки тоже читаются).

## Готовое приложение

Собранная версия лежит в `dist\LevitaDisplay`:

- `LevitaDisplay.exe` — панель управления (запуск/остановка, папка, настройки,
  автозапуск, OpenRGB, отключение MSI);
- `LevitaService.exe` — отдельная служба для автозапуска (трей, без окна).

На рабочем столе и в меню Пуск создан ярлык **Levita Display**. Автозапуск
(папка Startup) запускает `LevitaService.exe --tray`.

Панель держит службу внутри себя; автозапуск и ручной запуск не конфликтуют:
GUI при старте останавливает отдельную службу и забирает экран.

Пересборка:

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name LevitaDisplay ^
  --icon assets\icon.ico --add-data "assets;assets" --add-data "config.toml;." ^
  --add-data "tools;tools" --collect-all trcc --collect-binaries libusb_package ^
  --hidden-import win32com.client --hidden-import pythoncom entry.py

.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed --name LevitaService ^
  --icon assets\icon.ico --add-data "assets;assets" --add-data "config.toml;." ^
  --collect-all trcc --collect-binaries libusb_package service_entry.py
```

## Что умеет

- GIF, WebP, PNG/JPG и **MP4/WebM/MOV** из папки `gifs`;
- **кэш воспроизведения**: крупные GIF (2400×1080) и 4K-видео один раз
  пережимаются ffmpeg в 1600p MP4 (`.cache/media/`) и играют на 60 fps без
  нагрузки; новый файл кэшируется при первом показе;
- подгонка под холст 1600×720: обрезка до 20% площади, иначе вписывание с
  размытым фоном из самого кадра;
- палитра кадра (k-means) со сглаживанием → цвет ARGB через OpenRGB:
  берётся доминирующий по площади цвет, чёрный пропускается, близкие оттенки
  смешиваются;
- ротация по таймеру с кроссфейдом, история показов без частых повторов;
- вывод на реальный экран (bulk-протокол через trcc-linux) или в окно
  предпросмотра;
- трей Windows: пауза, следующий ролик, выход;
- переподключение при потере USB, один экземпляр приложения, автозапуск.

## Требования

- Windows 11, Python 3.10+ (проверено на 3.15.2);
- **ffmpeg** в PATH (для кэша крупных GIF/4K; без него они играют как есть);
- OpenRGB с включённым SDK-сервером (`OpenRGB.exe --server --startminimized`),
  запущенный от администратора (нужен для SMBus).

LibreHardwareMonitor и права администратора для датчиков больше не нужны.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

## Запуск

```powershell
.\.venv\Scripts\python main.py                 # окно предпросмотра
.\.venv\Scripts\pythonw.exe main.py --backend trcc   # реальный экран + трей
```

Полезные ключи: `--fps 60`, `--only имя`, `--no-rgb`, `--headless`,
`--frames N`, `--save-frames DIR`, `--exit-after SEC`.

Папка по умолчанию — `gifs` рядом с `main.py`; переопределяется
`--gif-folder` или `[media] folder` в `config.toml`.

Крупные файлы кэшируются автоматически при первом показе (~3 с на файл).
Собрать кэш заранее для всей папки:

```powershell
.\.venv\Scripts\python tools\build_media_cache.py
```

Кэш лежит в `.cache/media/` и пересобирается, если исходник изменился.

Горячие клавиши в предпросмотре: `Esc` — выход, `Space` — пауза,
`→`/`N` — следующий, `M` — маска, `F` — полный экран.

## Подсветка (OpenRGB)

Настройки — секция `[rgb]`: `zone = "JARGB"` (какие зоны вести),
`zone_leds = 24` (размер зоны), `rate_hz`, `smooth_seconds`,
`fast_smooth_seconds`, `hue_jump_degrees`, `min_delta`.
Проверка без приложения: `python tools\rgb_test.py`.

OpenRGB должен быть запущен **с SDK-сервером**:
`OpenRGB.exe --server --startminimized` (иначе порт 6742 не слушает и цвета
никуда не уходят). MSI Center/Mystic Light перехватывают канал — приложение
закрывает их процессы само (`autokill_conflicts = true`), а службы можно
отключить скриптом от администратора:

```powershell
powershell -ExecutionPolicy Bypass -File tools\kill_conflicts.ps1
powershell -ExecutionPolicy Bypass -File tools\kill_conflicts.ps1 -Restore
```

Чтобы OpenRGB сам поднимался с сервером и правами администратора:

```powershell
powershell -ExecutionPolicy Bypass -File tools\install_openrgb_task.ps1
powershell -ExecutionPolicy Bypass -File tools\install_openrgb_task.ps1 -Uninstall
```

## Ежедневный режим

Иконка в трее: пауза, следующий GIF, выход. Второй экземпляр не запустится
(lock `.cache/levita.lock`). При потере USB приложение ждёт и переподключается
(5→60 с).

Автозапуск:

```powershell
powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1
powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -Uninstall
```

## Тесты

```powershell
.\.venv\Scripts\python -m pytest
```

## Структура

```
core/       конфиг, логирование, планировщик, single-instance
display/    DisplayBackend, preview, trcc_backend (реальный экран), headless
media/      каталог GIF/MP4, подгонка, палитра
rgb/        OpenRGB SDK-клиент и синхронизация цвета
ui/         иконка в трее
tools/      диагностика экрана, RGB, автозапуск, иконка
docs/       notes.md (журнал решений), protocol.md (протокол экрана)
```

## Лицензия

GPL-3.0-or-later. Вывод на экран использует
[trcc-linux](https://github.com/Lexonight1/thermalright-trcc-linux) (GPL-3.0);
авторство — в `NOTICE`.
