import asyncio
import os
import random
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
MINE_COOLDOWN_SEC = 3     # кулдаун накопания (в секундах)
BONUS_AMOUNT = 5000         # размер бонуса
BONUS_COOLDOWN_HOURS = 12   # раз в сколько часов доступен бонус

# --- РУДА ---
ORES = {
    "stone":  {"name": "🪨 Камень",        "price": 2,   "xp": 2},
    "iron":   {"name": "⚙️ Железная руда", "price": 8,   "xp": 10},
    "copper": {"name": "🥉 Медная руда",   "price": 20,  "xp": 30},
    "gold":   {"name": "💎 Золотая руда",  "price": 360,  "xp": 1000},
}

# --- КИРКИ ---
# power: за каждые 10 единиц — +1 руда сверху к обычной добыче
# level: минимальный уровень игрока для покупки
PICKAXES = [
    {"key": "wood",    "name": "🪵 Деревянная", "power": 1,  "price": 10,     "level": 1},
    {"key": "stone",   "name": "🪨 Каменная",   "power": 3,  "price": 500,   "level": 4},
    {"key": "iron",    "name": "⚙️ Железная",   "power": 10, "price": 2500,  "level": 10},
    {"key": "gold",    "name": "💰 Золотая",    "power": 25, "price": 10000, "level": 20},
    {"key": "diamond", "name": "💎 Алмазная",   "power": 50, "price": 50000, "level": 50},
]

PICKAXE_BY_KEY = {p["key"]: p for p in PICKAXES}

# --- УРОВНИ ---
# Чтобы перейти с уровня N на N+1, нужно N * 500 опыта
def xp_needed_for_next_level(level):
    return level * 500

# --- БАЗА ДАННЫХ ---
DB_NAME = "bot_db.sqlite"

def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            pickaxe_key TEXT DEFAULT 'wood',
            last_mine_at TEXT,
            last_bonus_at TEXT
        )
    """)
    # если база старая — добавляем колонку про бонус
    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_bonus_at TEXT")
    except sqlite3.OperationalError:
        pass
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
        "last_bonus_at": row[7],
    }

def create_user(user_id, username):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, username, balance, xp, level, pickaxe_key, last_mine_at, last_bonus_at) "
        "VALUES (?, ?, 0, 0, 1, 'wood', NULL, NULL)",
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
    return datetime.now() >= last + timedelta(seconds=MINE_COOLDOWN_SEC)

def can_bonus(user):
    if not user["last_bonus_at"]:
        return True
    last = datetime.fromisoformat(user["last_bonus_at"])
    return datetime.now() >= last + timedelta(hours=BONUS_COOLDOWN_HOURS)

def seconds_until_mine(user):
    last = datetime.fromisoformat(user["last_mine_at"])
    end = last + timedelta(seconds=MINE_COOLDOWN_SEC)
    return max(0, int((end - datetime.now()).total_seconds()))

def hours_until_bonus(user):
    last = datetime.fromisoformat(user["last_bonus_at"])
    end = last + timedelta(hours=BONUS_COOLDOWN_HOURS)
    total_min = max(0, int((end - datetime.now()).total_seconds() // 60))
    return total_min // 60, total_min % 60

def add_xp_and_level_up(user_id, user, gained_xp):
    """Добавляет опыт и поднимает уровень, если накоплено достаточно. Возвращает новый уровень и кол-во повышений."""
    new_xp = user["xp"] + gained_xp
    new_level = user["level"]
    levelups = 0
    while new_xp >= xp_needed_for_next_level(new_level):
        new_xp -= xp_needed_for_next_level(new_level)
        new_level += 1
        levelups += 1
    update_user(user_id, xp=new_xp, level=new_level)
    return new_level, levelups

# --- КЛАВИАТУРЫ ---
def main_keyboard():
    kb = [
        [KeyboardButton(text="⛏ Накопать")],
        [KeyboardButton(text="🎁 Бонус")],
        [KeyboardButton(text="💼 Профиль"), KeyboardButton(text="🛒 Магазин")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def shop_keyboard():
    kb = [[KeyboardButton(text=f"⚒ Купить {p['name']}")] for p in PICKAXES if p["price"] > 0]
    kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    user = get_user(user_id)
    if not user:
        create_user(user_id, username)
        await message.answer(
            f"Привет, {username}! Ты стал шахтёром.\n"
            "У тебя есть деревянная кирка. Копай руду, качай уровни и покупай кирки получше!\n"
            "🎁 Бонус 5000 монет доступен раз в 12 часов."
        )
    else:
        pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
        await message.answer(f"Снова привет, {username}! Твоя кирка: {pick['name']}, уровень {user['level']}.")
    await message.answer("Выбери действие:", reply_markup=main_keyboard())

@dp.message(F.text == "⛏ Накопать")
async def mine_action(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.username or str(user_id))
        user = get_user(user_id)

    if not can_mine(user):
        await message.answer(f"Подожди ещё {seconds_until_mine(user)} сек. перед следующей добычей.")
        return

    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    bonus_from_pick = pick["power"] // 10       # +1 руда за каждые 10 силы кирки
    bonus_from_level = user["level"] - 1        # +1 руда за каждый уровень

    # Базовая добыча: 2–4 камня
    stone_count = random.randint(2, 4) + bonus_from_pick + bonus_from_level

    # Шансы на руду покруче растут вместе с киркой и уровнем
    iron_chance = 0.2 + pick["power"] / 200 + (user["level"] - 1) / 100
    copper_chance = 0.1 + pick["power"] / 400 + (user["level"] - 1) / 200
    gold_chance = 0.05 + pick["power"] / 800 + (user["level"] - 1) / 400

    iron_count = random.randint(1, 2) if random.random() < iron_chance else 0
    copper_count = random.randint(1, 2) if random.random() < copper_chance else 0
    gold_count = 1 if random.random() < gold_chance else 0

    total_xp = (
        stone_count * ORES["stone"]["xp"]
        + iron_count * ORES["iron"]["xp"]
        + copper_count * ORES["copper"]["xp"]
        + gold_count * ORES["gold"]["xp"]
    )
    total_money = (
        stone_count * ORES["stone"]["price"]
        + iron_count * ORES["iron"]["price"]
        + copper_count * ORES["copper"]["price"]
        + gold_count * ORES["gold"]["price"]
    )

    new_balance = user["balance"] + total_money
    update_user(user_id, balance=new_balance, last_mine_at=datetime.now().isoformat())
    new_level, levelups = add_xp_and_level_up(user_id, user, total_xp)

    text = "Ты накопал:\n"
    if stone_count > 0:
        text += f"🪨 Камень × {stone_count}\n"
    if iron_count > 0:
        text += f"⚙️ Железная руда × {iron_count}\n"
    if copper_count > 0:
        text += f"🥉 Медная руда × {copper_count}\n"
    if gold_count > 0:
        text += f"💎 Золотая руда × {gold_count}\n"
    text += f"\n💰 Получено монет: {total_money}\n📈 Получено опыта: {total_xp}"
    if levelups > 0:
        text += f"\n🎉 Поздравляем! Новый уровень: {new_level}! Теперь руды будет больше."
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "🎁 Бонус")
async def bonus_action(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.username or str(user_id))
        user = get_user(user_id)

    if not can_bonus(user):
        hours, minutes = hours_until_bonus(user)
        await message.answer(f"Бонус будет доступен через {hours} ч. {minutes} мин.")
        return

    new_balance = user["balance"] + BONUS_AMOUNT
    update_user(user_id, balance=new_balance, last_bonus_at=datetime.now().isoformat())
    await message.answer(f"🎁 Ты получил бонус: {BONUS_AMOUNT} монет!\nСледующий — через {BONUS_COOLDOWN_HOURS} часов.")

@dp.message(F.text.startswith("⚒ Купить"))
async def buy_pickaxe(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    wanted_name = message.text.replace("⚒ Купить ", "")
    wanted = next((p for p in PICKAXES if p["name"] == wanted_name), None)
    if not wanted:
        await message.answer("Такой кирки нет в продаже.")
        return

    current_pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    if current_pick["key"] == wanted["key"]:
        await message.answer("У тебя уже есть эта кирка!")
        return

    keys = [p["key"] for p in PICKAXES]
    current_idx = keys.index(current_pick["key"])
    wanted_idx = keys.index(wanted["key"])
    if wanted_idx != current_idx + 1:
        await message.answer("Покупай по порядку: сначала каменную, потом железную и т.д.")
        return

    if user["level"] < wanted["level"]:
        await message.answer(
            f"Не хватает уровня. Нужен уровень {wanted['level']}, у тебя {user['level']}.\n"
            "Копай больше — получай опыт и качайся!"
        )
        return

    if user["balance"] < wanted["price"]:
        await message.answer(f"Не хватает монет. Нужно {wanted['price']}, у тебя {user['balance']}.")
        return

    new_balance = user["balance"] - wanted["price"]
    update_user(user_id, balance=new_balance, pickaxe_key=wanted["key"])
    await message.answer(f"✅ Ты купил кирку: {wanted['name']}! Теперь копается лучше.")

@dp.message(F.text == "💼 Профиль")
async def profile(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return
    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    needed = xp_needed_for_next_level(user["level"])
    text = (
        f"👤 Профиль игрока {user['username']}\n"
        f"💰 Баланс: {user['balance']} монет\n"
        f"📈 Опыт: {user['xp']} / {needed} до уровня {user['level'] + 1}\n"
        f"🏅 Уровень: {user['level']}\n"
        f"⛏ Твоя кирка: {pick['name']}\n"
        f"Сила кирки даёт +{pick['power'] // 10} руды, уровень — ещё +{user['level'] - 1} руды за накопание.\n"
        f"⏰ Бонус: {'доступен' if can_bonus(user) else 'ещё не скоро'}"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "🛒 Магазин")
async def shop(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    lines = ["🛒 Магазин кирок (цена + требование уровня):"]
    for p in PICKAXES:
        if p["price"] > 0:
            lines.append(f"• {p['name']} — {p['price']} монет, нужен {p['level']} уровень")
    await message.answer("\n".join(lines), reply_markup=shop_keyboard())

@dp.message(F.text == "🔙 Назад")
async def back_to_main(message):
    await message.answer("Главное меню:", reply_markup=main_keyboard())

# --- ЗАПУСК ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
