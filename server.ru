import asyncio
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ ---
FARM_COOLDOWN = 5      # фарм раз в N секунд
FARM_REWARD = 10        # сколько монет за один фарм
BONUS_AMOUNT = 5000      # размер ежедневного бонуса
BONUS_COOLDOWN_HOURS = 12  # раз в сколько часов доступен бонус

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("farm.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            balance INTEGER DEFAULT 0,
            last_farm_at TEXT,
            last_bonus_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("farm.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, name, balance, last_farm_at, last_bonus_at FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "name": row[1], "balance": row[2],
                "last_farm_at": row[3], "last_bonus_at": row[4]}
    return None

def create_user(user_id, name):
    conn = sqlite3.connect("farm.db")
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)", (user_id, name))
    conn.commit()
    conn.close()

def update_balance(user_id, amount):
    conn = sqlite3.connect("farm.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def set_field(user_id, field, value):
    conn = sqlite3.connect("farm.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET " + field + " = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def get_top():
    conn = sqlite3.connect("farm.db")
    cur = conn.cursor()
    cur.execute("SELECT name, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    return rows

# --- КЛАВИАТУРА ---
def panel():
    kb = [
        [KeyboardButton(text="⛏ Фарм"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="🏆 Топ фермеров")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ХЕЛПЕРЫ ---
def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None

# --- ОБРАБОТЧИКИ ---
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Фермер"
    create_user(user_id, name)
    await message.answer(
        "🌾 <b>Ферма Фарма Прайм</b>\n\n"
        "Добро пожаловать на ферму!\n\n"
        "Жми «⛏ Фарм» — и получай урожай. "
        "Бонус можно забирать раз в сутки.",
        reply_markup=panel(),
    )

async def handle_farm(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.first_name or "Фермер")
        user = get_user(user_id)

    now = datetime.now()
    last = parse_dt(user["last_farm_at"])
    if last:
        diff = (now - last).total_seconds()
        if diff < FARM_COOLDOWN:
            await message.answer(f"⏳ Подожди ещё {int(FARM_COOLDOWN - diff)} с.")
            return

    update_balance(user_id, FARM_REWARD)
    set_field(user_id, "last_farm_at", now.isoformat())
    balance = get_user(user_id)["balance"]
    await message.answer(f"🧱 Ты добыл урожай! +{FARM_REWARD} монет. Баланс: {balance}")

async def handle_profile(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.first_name or "Фермер")
        user = get_user(user_id)
    await message.answer(
        f"👤 Профиль: {user['name']}\n"
        f"💰 Баланс: {user['balance']} монет\n"
        f"⛏ Последний фарм: {user['last_farm_at'] or 'ещё не было'}\n"
        f"🎁 Последний бонус: {user['last_bonus_at'] or 'не забирал'}"
    )

async def handle_bonus(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.first_name or "Фермер")
        user = get_user(user_id)

    now = datetime.now()
    last = parse_dt(user["last_bonus_at"])
    if last:
        hours = (now - last).total_seconds() / 3600
        if hours < BONUS_COOLDOWN_HOURS:
            left = int(BONUS_COOLDOWN_HOURS - hours) + 1
            await message.answer(f"🎁 Бонус уже забрал. Приходи через {left} ч.")
            return

    update_balance(user_id, BONUS_AMOUNT)
    set_field(user_id, "last_bonus_at", now.isoformat())
    await message.answer(f"🎉 Бонус получен: +{BONUS_AMOUNT} монет!")

async def handle_top(message: types.Message):
    rows = get_top()
    if not rows:
        await message.answer("🏆 Пока никто не фармит. Будь первым!")
        return
    lines = ["🏆 Топ фермеров:"]
    for i, (name, bal) in enumerate(rows, 1):
        lines.append(f"{i}. {name or 'Фермер'} — {bal} монет")
    await message.answer("\n".join(lines))

# --- ЗАПУСК ---
async def main():
    init_db()
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан! Добавь переменную BOT_TOKEN во вкладке «Переменные» в Bothost.")
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(handle_farm, lambda m: m.text == "⛏ Фарм")
    dp.message.register(handle_profile, lambda m: m.text == "👤 Профиль")
    dp.message.register(handle_bonus, lambda m: m.text == "🎁 Бонус")
    dp.message.register(handle_top, lambda m: m.text == "🏆 Топ фермеров")
    print("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
