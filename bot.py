import asyncio
import json
import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from openai import OpenAI

import storage

# Загружаем ключи из .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

for key, value in (("TELEGRAM_TOKEN", TELEGRAM_TOKEN), ("DEEPSEEK_API_KEY", DEEPSEEK_API_KEY)):
    if not value:
        raise SystemExit(f"Не задан {key} в .env")

# Настройка DeepSeek
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# Настройка Telegram
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

CONVERSATION_WINDOW_SIZE = 20
conversation = defaultdict(deque)

MAX_REPLY_TOKENS = 1200
REPORT_LISTING_THRESHOLD = 12

_TAG_RE = re.compile(r"</?(?:b|i|code|pre|s|u)>")
_HTML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))

# Системный промпт — характер бота
SYSTEM_PROMPT = Path(__file__).parent.joinpath("system_prompt.txt").read_text(encoding="utf-8")

# Промпт для извлечения намерения и данных о тренировке
EXTRACT_PROMPT = (
    "Ты определяешь намерение в сообщении пользователя и извлекаешь данные о тренировках. "
    "Верни ТОЛЬКО JSON без пояснений в формате: "
    '{{"intent": "workout"|"report"|"none", "period_from": string|null, "period_to": string|null, '
    '"kind": string|null, "details": string|null, "performed_at": string|null}}.\n'
    "intent: report — пользователь просит показать историю или отчёт о своих тренировках за период; "
    "workout — пользователь сообщает о реально выполненной тренировке или активности; "
    "none — всё остальное.\n"
    "period_from и period_to — только для intent=report: границы запрошенного периода в формате "
    "YYYY-MM-DD, обе включительные. Пользователь мог назвать период относительно "
    "(«за неделю», «за месяц») или календарный («в марте», «за 2024 год», «за лето») — считай границы "
    "от текущей даты, она указана ниже. Если период назван относительно, отсчитай его назад от текущей даты. "
    "Если пользователь не назвал период, используй разумный период по умолчанию (последние 7 дней). "
    "Если попросил показать всё время или всю историю — обе границы null. Если назвал только начало или только "
    "конец — заполни только соответствующую границу, вторую оставь null.\n"
    "kind — тип активности: силовая, кардио, бег и т.п.; только для intent=workout.\n"
    "details — кратко повтори, как именно тренировался пользователь (упражнения, веса, подходы).\n"
    "performed_at — время тренировки в ISO 8601 UTC. Текущая дата: {today} ({now}). "
    "Если пользователь не назвал время, считай, что тренировка сейчас.\n"
    "Не выдумывай ничего, чего пользователь не сообщил. Отсутствующие значения — null."
)

def strip_formatting(text):
    """Убирает теги оформления, чтобы реплика в переписке была чистым текстом."""
    cleaned = _TAG_RE.sub("", text)
    for char, escaped in _HTML_ESCAPES:
        cleaned = cleaned.replace(escaped, char)
    return cleaned


def escape_html(text):
    for char, escaped in _HTML_ESCAPES:
        text = text.replace(char, escaped)
    return text


async def send_reply(message, text):
    """Отправляет ответ с разметкой, а при отказе Telegram — без неё.

    Пользователь всегда получает текст: сначала пробуем разметку, при отказе
    отправляем экранированный текст и сообщаем о проблеме с оформлением.
    """
    try:
        await message.answer(text, parse_mode=ParseMode.HTML)
        return
    except TelegramBadRequest as e:
        print(f"Telegram отклонил разметку: {e}")
    await message.answer(
        escape_html(text)
        + "\n\n(Не смог оформить ответ — показал его без оформления.)",
        parse_mode=ParseMode.HTML,
    )


async def ask_deepseek(messages):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.7,
            max_tokens=MAX_REPLY_TOKENS
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Ошибка DeepSeek: {e}")
        return None
def _format_workout_line(w):
    label = f"{w['performed_at'][:10]} — {w['kind'] or 'тренировка'}"
    if w["details"]:
        label += f" ({w['details']})"
    return label


def build_workout_digest(user_id, limit=5):
    workouts = storage.get_workouts(user_id, limit=limit)
    if not workouts:
        return "Тренировок пока нет."
    lines = [_format_workout_line(w) for w in workouts]
    return "Последние тренировки пользователя:\n" + "\n".join(lines)


def _records_word(count):
    if count % 10 == 1 and count % 100 != 11:
        return "запись"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "записи"
    return "записей"


def build_report_context(user_id, period_from=None, period_to=None):
    workouts = storage.get_workouts(user_id, period_from=period_from, period_to=period_to)
    if not workouts:
        return "Тренировок за запрошенный период нет."
    count = len(workouts)
    header = f"Тренировки пользователя за запрошенный период: {count} {_records_word(count)}."
    lines = [_format_workout_line(w) for w in workouts]
    return header + "\n" + "\n".join(lines)

async def extract_workout(user_text):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": EXTRACT_PROMPT.format(
                        today=datetime.now(timezone.utc).date().isoformat(),
                        now=datetime.now(timezone.utc).isoformat(),
                    ),
                },
                {"role": "user", "content": user_text}
            ],
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as e:
        print(f"Ошибка извлечения данных: {e}")
        return None

# Обработчик команды /start
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        "Я LifeKickBot — твой тренер по образу жизни.\n"
        "Буду следить за тренировками, едой и привычками, чтобы прогресс не сливался.\n"
        "Пиши, что ел, как тренировался или что чувствуешь. Спроси отчёт — соберу по данным."
    )

# Обработчик всех остальных сообщений
@dp.message()
async def ai_handler(message: types.Message):
    if not message.text:
        await message.answer("Пока я читаю только текстовые сообщения. Напиши, что съел или как прошла тренировка.")
        return
    user_id = message.from_user.id
    user_text = message.text

    extraction = await extract_workout(user_text)
    intent = extraction.get("intent") if extraction else None

    facts_content = None
    if intent == "workout":
        now = datetime.now(timezone.utc).isoformat()
        storage.save_workout(
            user_id=user_id,
            performed_at=extraction.get("performed_at") or now,
            reported_at=now,
            kind=extraction.get("kind"),
            details=extraction.get("details"),
        )
        facts_content = build_workout_digest(user_id)
    elif intent == "report":
        facts_content = build_report_context(
            user_id,
            period_from=extraction.get("period_from"),
            period_to=extraction.get("period_to"),
        )
    else:
        facts_content = build_workout_digest(user_id)

    history = conversation[user_id]
    history.append({"role": "user", "content": user_text})
    while len(history) > CONVERSATION_WINDOW_SIZE:
        history.popleft()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if facts_content:
        messages.append({"role": "system", "content": facts_content})
    messages.extend(history)

    reply = await ask_deepseek(messages)
    if not reply:
        await message.answer("Что-то пошло не так. Попробуй ещё раз чуть позже.")
        return
    history.append({"role": "assistant", "content": strip_formatting(reply)})
    while len(history) > CONVERSATION_WINDOW_SIZE:
        history.popleft()
    await send_reply(message, reply)

async def main():
    storage.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())