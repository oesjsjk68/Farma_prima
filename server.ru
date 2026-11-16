import asyncio
import os
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# ВСТАВЬ СЮДА СВОЙ ТОКЕН ОТ @BotFather
TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА_ЗДЕСЬ")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- НАСТРОЙКИ ---
MINE_COOLDOWN_SEC = 3  # кулдаун между добычей (в секундах)

# --- РУДА ---
ORES = {
    "stone":  {"name": "🪨 Камень",        "price": 2,   "xp": 2},
    "iron":   {"name": "⚙️ Железная руда", "price": 8,   "xp": 5},
    "copper": {"name": "🥉 Медная руда",   "price": 20,  "xp": 10},
    "gold":   {"name": "💎 Золотая руда",  "price": 60,  "xp": 25},
}

# --- КИРКИ ---
# power: за каждые 10 единиц — +1 руда сверху к обычной добыче
PICKAXES = [
    {"key": "wood",    "name": "🪵 Деревянная", "power": 0,   "price": 0},
    {"key": "stone",   "name": "🪨 Каменная",   "power": 3,   "price": 5000},
    {"key": "iron",    "name": "⚙️ Железная",   "power": 10,  "price": 25000},
    {"key": "gold",    "name": "💰 Золотая",    "power": 25,  "price": 1000000},
    {"key": "diamond", "name": "💎 Алмазная",   "power": 50,  "price": 5000000},
]

PICKAXE_BY_KEY = {p["key"]: p for p in PICKAXES}

# --- БАЗА ДАННЫХ ---
DB_NAME = "bot_db.sqlite"

def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # Таблица пользователей
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            pickaxe_key TEXT DEFAULT 'wood',
            last_mine_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "user_id": row[0],
        "username": row[1],
        "balance": row[2],
        "xp": row[3],
        "level": row[4],
        "pickaxe_key": row[5],
        "last_mine_at": row[6],
    }

def create_user(user_id, username):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, username, balance, xp, level, pickaxe_key, last_mine_at) "
        "VALUES (?, ?, 0, 0, 1, 'wood', NULL)",
        (user_id, username),
    )
    conn.commit()
    conn.close()

def update_user(user_id, **kwargs):
    fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
    values = list(kwargs.values()) + [user_id]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

def can_mine(user):
    if not user["last_mine_at"]:
        return True
    last = datetime.fromisoformat(user["last_mine_at"])
    cooldown_end = last + timedelta(seconds=MINE_COOLDOWN_SEC)
    return datetime.now() >= cooldown_end

# --- КЛАВИАТУРЫ ---
def main_keyboard():
    kb = [
        [KeyboardButton(text="⛏ Добыть руду")],
        [KeyboardButton(text="💼 Профиль"), KeyboardButton(text="🛒 Магазин")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def shop_keyboard():
    kb = [[KeyboardButton(text=f"⚒ Купить {p['name']}") for p in PICKAXES if p["price"] > 0]]
    kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=[row for row in kb if row], resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    user = get_user(user_id)
    if not user:
        create_user(user_id, username)
        await message.answer(f"Привет, {username}! Ты стал шахтёром. У тебя есть дерев
[16.11.2026 15:11] prime son 1wpm: янная кирка.")
    else:
        await message.answer(f"Снова привет, {username}. Твоя кирка: {PICKAXE_BY_KEY[user['pickaxe_key']]['name']}.")
    await message.answer("Выбери действие:", reply_markup=main_keyboard())

@dp.message(F.text == "⛏ Добыть руду")
async def mine_action(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        # на всякий случай
        username = message.from_user.username or str(user_id)
        create_user(user_id, username)
        user = get_user(user_id)

    if not can_mine(user):
        last = datetime.fromisoformat(user["last_mine_at"])
        cooldown_end = last + timedelta(seconds=MINE_COOLDOWN_SEC)
        wait_seconds = int((cooldown_end - datetime.now()).total_seconds())
        if wait_seconds < 0:
            wait_seconds = 0
        await message.answer(f"Подожди ещё {wait_seconds} сек. перед следующей добычей.")
        return

    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    bonus_ores = pick["power"] // 10  # +1 руда за каждые 10 силы

    # Базовая добыча: 2–4 камня
    base_stone = random.randint(2, 4)
    stone_count = base_stone + bonus_ores

    # С шансом 20% ещё и железная руда
    iron_count = 0
    if random.random() < 0.2:
        iron_count = random.randint(1, 3) + (bonus_ores // 2)

    total_xp = (stone_count * ORES["stone"]["xp"]) + (iron_count * ORES["iron"]["xp"])
    total_money = (stone_count * ORES["stone"]["price"]) + (iron_count * ORES["iron"]["price"])

    new_balance = user["balance"] + total_money
    new_xp = user["xp"] + total_xp

    update_user(
        user_id,
        balance=new_balance,
        xp=new_xp,
        last_mine_at=datetime.now().isoformat(),
    )

    text = f"Ты добыл:\n"
    if stone_count > 0:
        text += f"🪨 Камень × {stone_count}\n"
    if iron_count > 0:
        text += f"⚙️ Железная руда × {iron_count}\n"
    text += f"\n💰 Получено монет: {total_money}\n📈 Получено опыта: {total_xp}"
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text.startswith("⚒ Купить"))
async def buy_pickaxe(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    # Найти, какую кирку хотят купить
    wanted_name = message.text.replace("⚒ Купить ", "")
    wanted = next((p for p in PICKAXES if p["name"] == wanted_name), None)
    if not wanted:
        await message.answer("Такой кирки нет в продаже.")
        return

    current_pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    if current_pick["key"] == wanted["key"]:
        await message.answer("У тебя уже есть эта кирка!")
        return

    # Простая логика: покупать можно только следующую по списку
    current_idx = [p["key"] for p in PICKAXES].index(current_pick["key"])
    wanted_idx = [p["key"] for p in PICKAXES].index(wanted["key"])
    if wanted_idx != current_idx + 1:
        await message.answer("Покупай по порядку: сначала каменную, потом железную и т.д.")
        return

    if user["balance"] < wanted["price"]:
        await message.answer(f"Не хватает монет. Нужно {wanted['price']}, у тебя {user['balance']}.")
        return

    # Покупаем
    new_balance = user["balance"] - wanted["price"]
    update_user(user_id, balance=new_balance, pickaxe_key=wanted["key"])
    await message.answer(f"✅ Ты купил кирку: {wanted['name']}. Теперь твоя сила выше!")
    await message.answer("Что дальше?", reply_markup=main_keyboard())

@dp.message(F.text == "💼 Профиль")
async def profile(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return
    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    text = (
        f"👤 Профиль игрока\n"
        f"Баланс: {user['balance']} монет\n"
        f"Опыт: {user['xp']} XP\n"
        f"Уровень: {user['level']}\n"
        f"Твоя кирка: {pick['name']}\n"
        f"(сила даёт +{pick['power']//10} руды за каждый заход)"
    )
    await message.answer(text, reply_
[16.11.2026 15:11] prime son 1wpm: markup=main_keyboard())

@dp.message(F.text == "🛒 Магазин")
async def shop(message):
    await message.answer("Магазин кирок:", reply_markup=shop_keyboard())

@dp.message(F.text == "🔙 Назад")
async def back_to_main(message):
    await message.answer("Главное меню:", reply_markup=main_keyboard())

# --- ЗАПУСК ---
async def main():
    await dp.start_polling(bot)

if name == "main":
    asyncio.run(main())
