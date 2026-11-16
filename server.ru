mport asyncio
import sqlite3
import time
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,i
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

# ================== НАСТРОЙКИ ==================
FARM_COOLDOWN = 5      # кулдаун фарма, сек (можно 5)
FARM_MIN = 10           # минимальный доход за фарм
FARM_MAX = 50          # максимальный доход за фарм
BONUS_COOLDOWN = 864000  # кулдаун бонуса, сек (24 часа)
BONUS_AMOUNT = 500      # сумма ежедневного бонуса
DB_PATH = "farm.db"
# ===============================================

import os
TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

db = sqlite3.connect(DB_PATH)
db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    balance INTEGER DEFAULT 0,
    total_farmed INTEGER DEFAULT 0,
    last_farm INTEGER DEFAULT 0,
    last_bonus INTEGER DEFAULT 0
)
""")
db.commit()


def get_user(user_id: int, name: str):
    cur = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        db.execute("INSERT INTO users (user_id, name) VALUES (?, ?)", (user_id, name))
        db.commit()
        return db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row[1] != name:
        db.execute("UPDATE users SET name = ? WHERE user_id = ?", (name, user_id))
        db.commit()
    return db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def panel():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⛏ Фарм")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏆 Топ фермеров")],
            [KeyboardButton(text="🎁 Бонус")],
        ],
        resize_keyboard=True,
    )


@dp.message(CommandStart())
async def start(message: Message):
    get_user(message.from_user.id, message.from_user.first_name)
    await message.answer(
        "🌾 <b>Ферма Фарма Прайм</b>
"
        "Добро пожаловать на ферму!

"
        "Жми «⛏ Фарм» — и получай урожай. "
        "Бонус можно забирать раз в сутки.",
        reply_markup=panel(),
    )


@dp.message(F.text == "⛏ Фарм")
async def farm(message: Message):
    user = get_user(message.from_user.id, message.from_user.first_name)
    now = int(time.time())
    last = user[4] or 0
    left = FARM_COOLDOWN - (now - last)
    if left > 0:
        await message.answer(f"⏳ Подожди ещё {left} с, урожай не успевает вырасти.")
        return
    from random import randint
    earned = randint(FARM_MIN, FARM_MAX)
    db.execute(
        "UPDATE users SET balance = balance + ?, total_farmed = total_farmed + ?, "
        "last_farm = ? WHERE user_id = ?",
        (earned, earned, now, message.from_user.id),
    )
    db.commit()
    await message.answer(f"🌾 Урожай собран! +{earned} зерна.
Баланс: {user[2] + earned}")


@dp.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = get_user(message.from_user.id, message.from_user.first_name)
    await message.answer(
        f"👤 <b>Профиль: {user[1]}</b>
"
        f"💰 Баланс: {user[2]} зерна
"
        f"📈 Всего нафармлено: {user[3]}"
    )


@dp.message(F.text == "🎁 Бонус")
async def bonus(message: Message):
    user = get_user(message.from_user.id, message.from_user.first_name)
    now = int(time.time())
    last = user[5] or 0
    left = BONUS_COOLDOWN - (now - last)
    if left > 0:
        hours = left // 3600
        minutes = (left % 3600) // 60
        await message.answer(f"🎁 Бонус уже забран. Приходи через {hours} ч {minutes} мин.")
        return
    db.execute(
        "UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id = ?",
        (BONUS_AMOUNT, now, message.from_user.id),
    )
    db.commit()
    await message.answer(f"🎁 Ежедневный бонус: +{BONUS_AMOUNT} зерна!
Баланс: {user[2] + BONUS_AMOUNT}")


@dp.message(F.text == "🏆 Топ фермеров")
async def top(message: Message):
    rows = db.execute(
        "SELECT name, balance FROM users ORDER BY balance DESC LIMIT 10"
    ).fetchall()
    lines = [f"{i + 1}. {name} — {bal}" for i, (name, bal) in enumerate(rows)]
    await message.answer("🏆 <b>Топ фермеров</b>

" + "
".join(lines))


async def main():
    print("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
