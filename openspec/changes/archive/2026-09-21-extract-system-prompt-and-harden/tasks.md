## 1. Вынос системного промпта

- [x] 1.1 Создать `system_prompt.txt` в корне проекта с текущим текстом промпта из `bot.py:25-78` (без тройных кавычек, с завершающим переводом строки)
- [x] 1.2 В `bot.py` удалить inline-`SYSTEM_PROMPT` и заменить на загрузку: `from pathlib import Path`; `SYSTEM_PROMPT = Path(__file__).parent.joinpath("system_prompt.txt").read_text(encoding="utf-8")`

## 2. Валидация конфигурации

- [x] 2.1 После `load_dotenv()` добавить проверку `TELEGRAM_TOKEN` и `DEEPSEEK_API_KEY` на наличие и непустоту; при пустом ключе выводить сообщение с именем недостающего ключа и завершать запуск (`raise SystemExit`)

## 3. Устойчивость хендлеров

- [x] 3.1 В `ai_handler` добавить guard: если `message.text` отсутствует (фото/стикер/голос/документ) — отвечать сообщением «пока принимаю только текст» и не вызывать DeepSeek
- [x] 3.2 В `ask_deepseek` обернуть `client.chat.completions.create` в `try/except`, логировать ошибку и возвращать `None` при сбое
- [x] 3.3 В `ai_handler` обработать результат `ask_deepseek`: при `None` или пустом `content` отвечать fallback-сообщением о временной проблеме; `message.answer` обернуть в `try/except` с логированием

## 4. Проверка

- [x] 4.1 Запустить `venv/bin/python -m py_compile bot.py` и убедиться, что синтаксис корректен
- [x] 4.2 При запуске без `.env` убедиться, что появляется сообщение о недостающем ключе (визуально, `venv/bin/python bot.py` прерывается с SystemExit)