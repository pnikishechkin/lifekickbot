import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from openai import OpenAI

# Загружаем ключи из .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Настройка DeepSeek
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# Настройка Telegram
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Системный промпт — характер бота
SYSTEM_PROMPT = """
Ты — LifeKickBot, дерзкий друг, который помогает следить за здоровьем.
Твой стиль:
- Короткие фразы (1-3 предложения).
- Дружеский, но с подколами.
- Если пользователь ленится — пинай его.
- Не используй эмодзи слишком часто (максимум 1 на сообщение).
"""

async def ask_deepseek(user_text):
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
    user_text = message.text
    reply = await ask_deepseek(user_text)
    await message.answer(reply)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())