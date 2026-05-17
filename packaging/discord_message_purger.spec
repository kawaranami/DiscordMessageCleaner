# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec-файл для сборки Discord Message Purger в один .exe.

Использование:
    pyinstaller packaging/discord_message_purger.spec

Результат: dist/DiscordMessagePurger.exe — автономный исполняемый файл
для Windows, не требующий установленного Python.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Корень проекта — на один уровень выше каталога packaging/
_PROJECT_ROOT = Path(SPECPATH).parent

# Точка входа приложения
_ENTRY_POINT = str(_PROJECT_ROOT / "src" / "discord_message_purger" / "__main__.py")

# --- Сбор данных PySide6 (плагины, переводы, QML и т.д.) ---
# PySide6 требует runtime-файлы: плагины платформ, стилей, иконок.
_pyside6_datas = collect_data_files("PySide6", includes=["plugins/**", "translations/**"])

# --- Скрытые импорты ---
# PySide6 динамически загружает модули; перечисляем явно.
_pyside6_hiddenimports = collect_submodules("PySide6")

# --- Исключения: тестовые пакеты и dev-зависимости не нужны в бандле ---
_excludes = [
    "pytest",
    "pytest_qt",
    "hypothesis",
    "respx",
    "freezegun",
    "unittest",
    "test",
    "tests",
    "tkinter",
    "_tkinter",
]

# =============================================================================
# Анализ зависимостей
# =============================================================================
a = Analysis(
    [_ENTRY_POINT],
    pathex=[str(_PROJECT_ROOT / "src")],
    binaries=[],
    datas=_pyside6_datas,
    hiddenimports=_pyside6_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
)

# =============================================================================
# Упаковка в один архив (onefile)
# =============================================================================
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DiscordMessagePurger",       # Имя выходного файла
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                          # Сжатие UPX, если доступен
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                     # Оконное приложение — лог пишется в файл
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                         # Иконка пока не задана
)
