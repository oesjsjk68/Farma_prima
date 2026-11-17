import os
import sqlite3
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup,
)
from aiogram.enums import ParseMode

DB_NAME = "bot_db.sqlite"

bot = Bot(token=os.environ.get("BOT_TOKEN", ""))
dp = Dispatcher()

ORE_NAMES = {
    "stone": "Камень",
    "iron": "Железная руда",
    "copper": "Медная руда",
    "gold": "Золотая руда",
}
ORE_EMOJI = {"stone": "🪨", "iron": "⚙️", "copper": "🥉", "gold": "💎"}
PICK_NAMES = {
    "wood": "Деревянная", "stone": "Каменная", "iron": "Железная",
    "gold": "Золотая", "diamond": "Алмазная",
}
PICK_ORDER = ["wood", "stone", "iron", "gold", "diamond"]
PICK_BONUS = {"wood": 1, "stone": 2, "iron": 4, "gold": 8, "diamond": 15}
PICK_UPGRADE_COST = {"wood": 0, "stone": 500, "iron": 2500, "gold": 10000, "diamond": 50000}

DEFAULT_SETTINGS = {"mine_cooldown": "3", "bonus_amount": "5000", "bonus_hours": "12"}
DEFAULT_PRICES = {"stone": 2, "iron": 8, "copper": 20, "gold": 60}


def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def ensure_tables():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        pickaxe_key TEXT DEFAULT 'wood',
        ore_stone INTEGER DEFAULT 0,
        ore_iron INTEGER DEFAULT 0,
        ore_copper INTEGER DEFAULT 0,
        ore_gold INTEGER DEFAULT 0,
        total_mined INTEGER DEFAULT 0,
        last_mine REAL DEFAULT 0,
        last_bonus REAL DEFAULT 0
    )""")
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS prices (ore_key TEXT PRIMARY KEY, price INTEGER)")
    for k, v in DEFAULT_SETTINGS.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    for k, v in DEFAULT_PRICES.items():
        cur.execute("INSERT OR IGNORE INTO prices (ore_key, price) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def get_setting(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return int(row[0]) if row else int(DEFAULT_SETTINGS[key])


def get_prices():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT ore_key, price FROM prices")
    prices = dict(cur.fetchall())
    conn.close()
    return {**DEFAULT_PRICES, **prices}


def get_user(telegram_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT telegram_id, username, balance, level, pickaxe_key,
                          ore_stone, ore_iron, ore_copper, ore_gold,
                          total_mined, last_mine, last_bonus
                   FROM users WHERE telegram_id = ?""", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row


def ensure_user(message: Message):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)",
        (message.from_user.id, message.from_user.username or message.from_user.first_name),
    )
    conn.commit()
    conn.close()


def update_user(telegram_id, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {sets} WHERE telegram_id = ?", (*fields.values(), telegram_id))
    conn.commit()
    conn.close()


def level_for(balance):
    return balance // 1000 + 1


MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⛏ Копать"), KeyboardButton(text="📦 Профиль")],
        [KeyboardButton(text="💰 Продать руду"), KeyboardButton(text="🎁 Бонус")],
        [KeyboardButton(text="⛏ Кирки"), KeyboardButton(text="🏆 Топ")],
    ],
    resize_keyboard=True,
)


def profile_text(user):
    _, username, balance, level, pick, o_s, o_i, o_c, o_g, total, _, last_bonus = user
    prices = get_prices()
    worth = o_s * prices["stone"] + o_i * prices["iron"] + o_c * prices["copper"] + o_g * prices["gold"]
    return (
        f"📦 <b>Профиль</b>\n"
        f"👤 {username}\n"
        f"💰 Монеты: <b>{balance}</b>\n"
        f"🏅 Уровень: <b>{level}</b>\n"
        f"⛏ Кирка: <b>{PICK_NAMES[pick]}</b>\n\n"
        f"🎒 Рюкзак:\n"
        f"{ORE_EMOJI['stone']} Камень: {o_s}\n"
        f"{ORE_EMOJI['iron']} Железо: {o_i}\n"
        f"{ORE_EMOJI['copper']} Медь: {o_c}\n"
        f"{ORE_EMOJI['gold']} Золото: {o_g}\n"
        f"— Суммарно на продажу: <b>{worth}</b> монет\n\n"
        f"📊 Всего накопано: <b>{total}</b>"
    )


@dp.message(CommandStart())
async def cmd_start(message: Message):
    ensure_tables()
    ensure_user(message)
    await message.answer(
        "⛏ Добро пожаловать в <b>Шахту</b>!\n\n"
        "Копай руду, продавай её, покупай кирки покруче и забирай бонус.\n"
        "Жми кнопки ниже — и вперёд!",
        reply_markup=MENU,
    )


@dp.message(F.text == "⛏ Копать")
async def mine(message: Message):
    ensure_user(message)
    user = get_user(message.from_user.id)
    if not user:
        return
    now = time.time()
    cooldown = get_setting("mine_cooldown")
    if now - user[10] < cooldown:
        await message.answer(f"⏳ Рано! Подожди {cooldown} секунд между накопаниями.")
        return
    import random
    pick = user[4]
    roll = random.random()
    if roll < 0.60:
        ore = "stone"
    elif roll < 0.85:
        ore = "iron"
    elif roll < 0.96:
        ore = "copper"
    else:
        ore = "gold"
    amount = PICK_BONUS[pick] + random.randint(0, 2)
    ore_col = f"ore_{ore}"
    total = user[9] + amount
    level = level_for(user[2])
    update_user(
        message.from_user.id,
        **{ore_col: user[5 + ["stone", "iron", "copper", "gold"].index(ore)] + amount},
        total_mined=total,
        last_mine=now,
        level=level,
    )
    await message.answer(
        f"⛏ Ты накопал: {ORE_EMOJI[ore]} <b>{ORE_NAMES[ore]}</b> ×{amount}!"
    )


@dp.message(F.text == "📦 Профиль")
async def profile(message: Message):
    ensure_user(message)
    user = get_user(message.from_user.id)
    if user:
        await message.answer(profile_text(user))


@dp.message(F.text == "💰 Продать руду")
async def sell(message: Message):
    ensure_user(message)
    user = get_user(message.from_user.id)
    if not user:
        return
    prices = get_prices()
    earned = (
        user[5] * prices["stone"]
        + user[6] * prices["iron"]
        + user[7] * prices["copper"]
        + user[8] * prices["gold"]
    )
    if earned == 0:
        await message.answer("🎒 Рюкзак пуст. Сначала накопай руду!")
        return
    new_balance = user[2] + earned
    update_user(
        message.from_user.id,
        balance=new_balance,
        ore_stone=0, ore_iron=0, ore_copper=0, ore_gold=0,
        level=level_for(new_balance),
    )
    await message.answer(f"💰 Продал весь рюкзак за <b>{earned}</b> монет!")


@dp.message(F.text == "⛏ Кирки")
async def picks(message: Message):
    ensure_user(message)
    user = get_user(message.from_user.id)
    if not user:
        return
    current = user[4]
    idx = PICK_ORDER.index(current)
    if idx >= len(PICK_ORDER) - 1:
        await message.answer("⛏ У тебя уже лучшая кирка — Алмазная!")
        return
    nxt = PICK_ORDER[idx + 1]
    cost = PICK_UPGRADE_COST[nxt]
    await message.answer(
        f"⛏ Твоя кирка: <b>{PICK_NAMES[current]}</b>\n"
        f"Следующая: <b>{PICK_NAMES[nxt]}</b> (добывает больше)\n"
        f"Цена: <b>{cost}</b> монет",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=f"Купить {PICK_NAMES[nxt]}")]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )


@dp.message(F.text.startswith("Купить "))
async def buy_pick(message: Message):
    ensure_user(message)
    user = get_user(message.from_user.id)
    if not user:
        return
    name = message.text.replace("Купить ", "")
    target = next((k for k, v in PICK_NAMES.items() if v == name), None)
    if not target or PICK_ORDER.index(target) != PICK_ORDER.index(user[4]) + 1:
        return
    cost = PICK_UPGRADE_COST[target]
    if user[2] < cost:
        await message.answer(f"💸 Не хватает монет! Нужно <b>{cost}</b>, у тебя {user[2]}.")
        return
    update_user(message.from_user.id, balance=user[2] - cost, pickaxe_key=target)
    await message.answer(f"🎉 Поздравляю! Теперь у тебя <b>{PICK_NAMES[target]}</b> кирка!")


@dp.message(F.text == "🎁 Бонус")
async def bonus(message: Message):
    ensure_user(message)
    user = get_user(message.from_user.id)
    if not user:
        return
    now = time.time()
    hours = get_setting("bonus_hours")
    amount = get_setting("bonus_amount")
    if now - user[11] < hours * 3600:
        left = int((hours * 3600 - (now - user[11])) // 60)
        await message.answer(f"⏳ Бонус уже забрал. Жди ещё {left} мин.")
        return
    new_balance = user[2] + amount
    update_user(message.from_user.id, balance=new_balance, last_bonus=now, level=level_for(new_balance))
    await message.answer(f"🎁 Бонус <b>{amount}</b> монет зачислен!")


@dp.message(F.text == "🏆 Топ")
async def top(message: Message):
    ensure_tables()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    lines = ["🏆 <b>Топ игроков</b>\n"]
    for i, (name, bal) in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(f"{medal} {name} — {bal} монет")
    await message.answer("\n".join(lines))


async def main():
    ensure_tables()
    await dp.start_polling(bot)
