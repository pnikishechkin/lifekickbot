import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from openai import OpenAI

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

# Системный промпт — характер бота
SYSTEM_PROMPT = Path(__file__).parent.joinpath("system_prompt.txt").read_text(encoding="utf-8")

async def ask_deepseek(user_text):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Ошибка DeepSeek: {e}")
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
    user_text = message.text
    reply = await ask_deepseek(user_text)
    if not reply:
        await message.answer("Что-то пошло не так. Попробуй ещё раз чуть позже.")
        return
    try:
        await message.answer(reply)
    except Exception as e:
        print(f"Ошибка отправки ответа: {e}")
        await message.answer("Что-то пошло не так. Попробуй ещё раз чуть позже.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())