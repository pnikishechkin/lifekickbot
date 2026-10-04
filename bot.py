import asyncio
import json
import os
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
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

# Системный промпт — характер бота
SYSTEM_PROMPT = Path(__file__).parent.joinpath("system_prompt.txt").read_text(encoding="utf-8")

# Промпт для извлечения намерения и данных о тренировке
EXTRACT_PROMPT = (
    "Ты определяешь намерение в сообщении пользователя и извлекаешь данные о тренировках. "
    "Верни ТОЛЬКО JSON без пояснений в формате: "
    '{{"intent": "workout"|"report"|"none", "report_period": "day"|"week"|"month"|"all"|null, '
    '"kind": string|null, "details": string|null, "performed_at": string|null}}.\n'
    "intent: report — пользователь просит показать историю или отчёт о своих тренировках за период; "
    "workout — пользователь сообщает о реально выполненной тренировке или активности; "
    "none — всё остальное.\n"
    "report_period — только для intent=report: запрошенный период (день/неделя/месяц/всё время), иначе null.\n"
    "kind — тип активности: силовая, кардио, бег и т.п.; только для intent=workout.\n"
    "details — кратко повтори, как именно тренировался пользователь (упражнения, веса, подходы).\n"
    "performed_at — время тренировки в ISO 8601 UTC. Текущее время UTC: {now}. "
    "Если пользователь не назвал время, считай, что тренировка сейчас.\n"
    "Не выдумывай ничего, чего пользователь не сообщил. Отсутствующие значения — null."
)

async def ask_deepseek(messages):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Ошибка DeepSeek: {e}")
        return None

def build_workout_digest(user_id, limit=5):
    workouts = storage.get_workouts(user_id, limit=limit)
    if not workouts:
        return "Тренировок пока нет."
    lines = []
    for w in workouts:
        label = f"{w['performed_at'][:10]} — {w['kind'] or 'тренировка'}"
        if w["details"]:
            label += f" ({w['details']})"
        lines.append(label)
    return "Последние тренировки пользователя:\n" + "\n".join(lines)

def period_since(period):
    if period == "day":
        return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    if period == "week":
        return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    if period == "month":
        return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    return None

def build_report_context(user_id, period):
    since = period_since(period)
    workouts = storage.get_workouts(user_id, since=since) if since else storage.get_workouts(user_id)
    if not workouts:
        return "Тренировок за запрошенный период нет."
    lines = []
    for w in workouts:
        label = f"{w['performed_at'][:10]} — {w['kind'] or 'тренировка'}"
        if w["details"]:
            label += f" ({w['details']})"
        lines.append(label)
    return "Тренировки пользователя за запрошенный период:\n" + "\n".join(lines)

async def extract_workout(user_text):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": EXTRACT_PROMPT.format(now=datetime.now(timezone.utc).isoformat())},
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
        "Йо! Я LifeKickBot.\n"
        "Буду следить, чтобы ты не превратился в диванную подушку.\n"
        "Кидай мне, что ел, как тренировался, или просто пиши о самочувствии."
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
        facts_content = build_report_context(user_id, extraction.get("report_period"))
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
    history.append({"role": "assistant", "content": reply})
    while len(history) > CONVERSATION_WINDOW_SIZE:
        history.popleft()
    try:
        await message.answer(reply)
    except Exception as e:
        print(f"Ошибка отправки ответа: {e}")
        await message.answer("Что-то пошло не так. Попробуй ещё раз чуть позже.")

async def main():
    storage.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())