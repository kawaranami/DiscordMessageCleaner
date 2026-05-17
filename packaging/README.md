# Сборка дистрибутива

## Требования

- Python 3.11+
- Установленные зависимости проекта: `pip install -e .[dev]`
- PyInstaller: `pip install pyinstaller>=6.0`

## Сборка одного .exe

Из корня проекта выполните:

```bash
pyinstaller packaging/discord_message_purger.spec
```

Результат появится в `dist/DiscordMessagePurger.exe`.

## Что делает spec-файл

- Точка входа: `src/discord_message_purger/__main__.py`
- Режим: один файл (`onefile=True`)
- Тип окна: GUI без консоли (`console=False`)
- Включает плагины и данные PySide6 (платформы, стили, переводы)
- Исключает тестовые пакеты (`pytest`, `hypothesis`, `respx`, `freezegun`, `tkinter`)
- Сжатие UPX (если утилита доступна в PATH)
- Иконка: пока не задана (`icon=None`)

## Устранение проблем

- Если при запуске .exe возникает ошибка «Failed to load platform plugin "windows"», убедитесь, что плагины PySide6 корректно собраны. Попробуйте пересобрать с флагом `--clean`:
  ```bash
  pyinstaller --clean packaging/discord_message_purger.spec
  ```
- Для отладки добавьте `console=True` в spec-файле и пересоберите — ошибки будут выводиться в терминал.
