# Makefile для Discord Message Purger
# Цели: build, test, lint, clean

.PHONY: build test lint clean

# Сборка одного .exe через PyInstaller
build:
	pyinstaller packaging/discord_message_purger.spec --clean

# Запуск тестов
test:
	pytest

# Линтинг (при наличии ruff или flake8)
lint:
	python -m ruff check src/ tests/ || python -m flake8 src/ tests/

# Очистка артефактов сборки
clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
