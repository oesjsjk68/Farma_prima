import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

# Получаем токен из переменных окружения (Bothost сам его подставит)
API_TOKEN = os.getenv("BOT_TOKEN")

if not API_TOKEN:
    raise ValueError("Токен бота не найден! Проверьте переменную окружения BOT_TOKEN в панели Bothost.")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Хранилище кулдаунов (в памяти, сбросится при перезапуске бота)
# Для продакшена лучше использовать Redis или базу данных
user_cooldowns = {}

COOLDOWN_SECONDS = 60  # Кулдаун 60 секунд

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для фарма.\n"
        "Нажми /farm, чтобы начать фармить.\n"
        f"Между фармами есть пауза: {COOLDOWN_SECONDS} сек."
    )

@dp.message(Command("farm"))
async def cmd_farm(message: types.Message):
    user_id = message.from_user.id
    current_time = asyncio.get_event_loop().time()

    # Проверка кулдауна
    if user_id in user_cooldowns:
        time_left = COOLDOWN_SECONDS - (current_time - user_cooldowns[user_id])
        if time_left > 0:
            await message.answer(f"Подожди еще {int(time_left)} сек. перед следующим фармом!")
            return

    # Если кулдаун прошел или его не было
    await message.answer("⛏️ Начинаю фармить... (это займет пару секунд)")
    
    # Имитация работы (задержка)
    await asyncio.sleep(2) 
    
    # Тут должна быть логика твоего фарма (запросы к API, клики и т.д.)
    # Сейчас просто выдаем результат
    await message.answer("✅ Фарм завершен! Получено 100 монет.")

    # Обновляем время последнего использования
    user_cooldowns[user_id] = current_time

async def main():
    print("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
