import asyncio
import os
import random
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА_ЗДЕСЬ")

ADMIN_IDS = {5636309834}

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- НАСТРОЙКИ ---
MINE_COOLDOWN_SEC = 3
BONUS_AMOUNT = 5000
BONUS_COOLDOWN_HOURS = 12
ROULETTE_COOLDOWN_SEC = 30
ROULETTE_MIN_LEVEL = 20

# --- СКИДКИ ---
# 1% за каждую покупку кирки, максимум 15%
DISCOUNT_PER_PURCHASE = 1
DISCOUNT_MAX = 15
# Возврат последней покупки возможен в течение N минут
REFUND_WINDOW_MIN = 15

# --- ЕЖЕДНЕВНЫЙ КЕЙС ---
CASE_COOLDOWN_HOURS = 24
# Награды кейса: (описание, шанс, тип, значение)
CASE_REWARDS = [
    {"name": "50 монет",                              "chance": 2,  "type": "money", "value": 50},
    {"name": "100 монет",                             "chance": 25, "type": "money", "value": 100},
    {"name": "500 монет",                             "chance": 20, "type": "money", "value": 500},
    {"name": "1000 монет",                            "chance": 20, "type": "money", "value": 1000},
    {"name": "5000 монет",                            "chance": 10, "type": "money", "value": 5000},
    {"name": "10000 монет",                           "chance": 4,  "type": "money", "value": 10000},
    {"name": "200 опыта",                             "chance": 10, "type": "xp",    "value": 200},
    {"name": "500 опыта",                             "chance": 6,  "type": "xp",    "value": 500},
    {"name": "💥 ДЖЕКПОТ: скидка 50% на следующую покупку!", "chance": 3, "type": "jackpot", "value": 50},
]

# --- ДЖЕКПОТ-СКИДКА ---
JACKPOT_DISCOUNT = 50          # размер джекпот-скидки, %
JACKPOT_VALID_HOURS = 24       # сколько часов действует (на следующую покупку)

# --- РУДА ---
ORES = {
    "stone":  {"name": "🪨 Камень",        "price": 2,  "xp": 2},
    "iron":   {"name": "⚪ Железная руда",  "price": 8,  "xp": 5},
    "copper": {"name": "🟤 Медная руда",    "price": 20, "xp": 10},
    "gold":   {"name": "🟡 Золотая руда",   "price": 60000, "xp": 25},
}
ORE_KEYS = ["stone", "iron", "copper", "gold"]

# --- КИРКИ ---
PICKAXES = [
    {"key": "wood",    "name": "🪵 Деревянная", "power": 0,  "price": 0,       "level": 1},
    {"key": "stone",   "name": "⛏️ Каменная",   "power": 3,  "price": 5000,    "level": 10},
    {"key": "iron",    "name": "⛏️ Железная",   "power": 10, "price": 250000,  "level": 20},
    {"key": "gold",    "name": "⛏️ Золотая",    "power": 25, "price": 1000000, "level": 35},
    {"key": "diamond", "name": "⛏️ Алмазная",   "power": 50, "price": 5000000, "level": 50},
]
PICKAXE_BY_KEY = {p["key"]: p for p in PICKAXES}

# --- РУЛЕТКА ---
ROULETTE_SECTORS = [
    {"name": "💥 Джекпот x5!",        "chance": 0.02, "mult": 5.0},
    {"name": "🔥 Крупный выигрыш x3", "chance": 0.08, "mult": 3.0},
    {"name": "✅ Выигрыш x2",          "chance": 0.20, "mult": 2.0},
    {"name": "➖ Ставка возвращается", "chance": 0.15, "mult": 1.0},
    {"name": "❌ Проигрыш",            "chance": 0.55, "mult": 0.0},
]
ROULETTE_MIN_BET = 10
ROULETTE_MAX_BET = 100000

def xp_needed_for_next_level(level):
    return level * 100

# --- БАЗА ДАННЫХ ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(SCRIPT_DIR, "bot_db.sqlite")

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
            last_bonus_at TEXT,
            ore_stone INTEGER DEFAULT 0,
            ore_iron INTEGER DEFAULT 0,
            ore_copper INTEGER DEFAULT 0,
            ore_gold INTEGER DEFAULT 0,
            last_case_at TEXT,
            jackpot_discount INTEGER DEFAULT 0,
            jackpot_until TEXT
        )
    """)
    # миграции для старых баз
    for col, dflt in [
        ("last_bonus_at", None), ("ore_stone", 0), ("ore_iron", 0),
        ("ore_copper", 0), ("ore_gold", 0),
        ("last_case_at", None), ("jackpot_discount", 0), ("jackpot_until", None),
    ]:
        try:
            if dflt is None:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
            else:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT {dflt}")
        except sqlite3.OperationalError:
            pass

    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS prices (ore_key TEXT PRIMARY KEY, price INTEGER)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchase_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            pickaxe_key TEXT,
            price INTEGER,
            refunded INTEGER DEFAULT 0,
            timestamp TEXT
        )
    """)
    try:
        cur.execute("ALTER TABLE purchase_history ADD COLUMN refunded INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    defaults = {
        "mine_cooldown": str(MINE_COOLDOWN_SEC),
        "bonus_amount": str(BONUS_AMOUNT),
        "bonus_hours": str(BONUS_COOLDOWN_HOURS),
        "case_hours": str(CASE_COOLDOWN_HOURS),
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    for k, v in ORES.items():
        cur.execute("INSERT OR IGNORE INTO prices (ore_key, price) VALUES (?, ?)", (k, v["price"]))

    conn.commit()
    conn.close()

init_db()

# --- ЖИВЫЕ НАСТРОЙКИ ИЗ БАЗЫ ---
def get_setting(key, default):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return default

def get_prices():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT ore_key, price FROM prices")
    result = dict(cur.fetchall())
    conn.close()
    return result

def set_setting(key, value):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def set_ore_price(ore_key, price):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO prices (ore_key, price) VALUES (?, ?)", (ore_key, price))
    conn.commit()
    conn.close()

# --- ИСТОРИЯ ПОКУПОК И СКИДКИ ---
def add_purchase(user_id, pickaxe_key, price):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO purchase_history (user_id, pickaxe_key, price, refunded, timestamp) VALUES (?, ?, ?, 0, ?)",
        (user_id, pickaxe_key, price, datetime.now().isoformat())
    )
    purchase_id = cur.lastrowid
    conn.commit()
    conn.close()
    return purchase_id

def get_purchase_history(user_id, limit=10):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT pickaxe_key, price, refunded, timestamp FROM purchase_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def get_last_purchase(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, pickaxe_key, price, timestamp FROM purchase_history WHERE user_id = ? AND refunded = 0 ORDER BY id DESC LIMIT 1",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()
    return row

def mark_refunded(purchase_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE purchase_history SET refunded = 1 WHERE id = ?", (purchase_id,))
    conn.commit()
    conn.close()

def get_discount(user_id):
    """Итоговая скидка: базовая (1% за покупку, макс 15%) + активный джекпот-скидка."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM purchase_history WHERE user_id = ? AND refunded = 0",
        (user_id,)
    )
    count = cur.fetchone()[0]
    conn.close()
    base = min(DISCOUNT_MAX, count * DISCOUNT_PER_PURCHASE)

    jackpot = 0
    user = get_user(user_id)
    if user and user["jackpot_discount"] and user["jackpot_until"]:
        try:
            until = datetime.fromisoformat(user["jackpot_until"])
            if datetime.now() <= until:
                jackpot = user["jackpot_discount"]
        except ValueError:
            pass
    return base + jackpot, base, jackpot

def consume_jackpot(user_id):
    """Списать джекпот-скидку после покупки."""
    update_user(user_id, jackpot_discount=0, jackpot_until=None)

# --- СОСТОЯНИЕ ---
pending_roulette = {}
pending_purchase = {}   # user_id -> pickaxe_key (ожидает подтверждения)
roulette_cooldowns = {}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    colnames = [d[0] for d in cur.description] if row else None
    conn.close()
    if row is None:
        return None
    d = dict(zip(colnames, row))
    d.setdefault("last_case_at", None)
    d.setdefault("jackpot_discount", 0)
    d.setdefault("jackpot_until", None)
    return d

def create_user(user_id, username):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
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
    return datetime.now() >= last + timedelta(seconds=get_setting("mine_cooldown", MINE_COOLDOWN_SEC))

def can_bonus(user):
    if not user["last_bonus_at"]:
        return True
    last = datetime.fromisoformat(user["last_bonus_at"])
    return datetime.now() >= last + timedelta(hours=get_setting("bonus_hours", BONUS_COOLDOWN_HOURS))

def can_case(user):
    if not user.get("last_case_at"):
        return True
    last = datetime.fromisoformat(user["last_case_at"])
    return datetime.now() >= last + timedelta(hours=get_setting("case_hours", CASE_COOLDOWN_HOURS))

def seconds_until_mine(user):
    last = datetime.fromisoformat(user["last_mine_at"])
    end = last + timedelta(seconds=get_setting("mine_cooldown", MINE_COOLDOWN_SEC))
    return max(0, int((end - datetime.now()).total_seconds()))

def hours_until_bonus(user):
    last = datetime.fromisoformat(user["last_bonus_at"])
    end = last + timedelta(hours=get_setting("bonus_hours", BONUS_COOLDOWN_HOURS))
    total_min = max(0, int((end - datetime.now()).total_seconds() // 60))
    return total_min // 60, total_min % 60

def hours_until_case(user):
    last = datetime.fromisoformat(user["last_case_at"])
    end = last + timedelta(hours=get_setting("case_hours", CASE_COOLDOWN_HOURS))
    total_min = max(0, int((end - datetime.now()).total_seconds() // 60))
    return total_min // 60, total_min % 60

def add_xp_and_level_up(user_id, user, gained_xp):
    new_xp = user["xp"] + gained_xp
    new_level = user["level"]
    levelups = 0
    while new_xp >= xp_needed_for_next_level(new_level):
        new_xp -= xp_needed_for_next_level(new_level)
        new_level += 1
        levelups += 1
    update_user(user_id, xp=new_xp, level=new_level)
    return new_level, levelups

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# --- КЛАВИАТУРЫ ---
def main_keyboard():
    kb = [
        [KeyboardButton(text="⛏️ Накопать")],
        [KeyboardButton(text="💰 Продать руду"), KeyboardButton(text="🎁 Бонус")],
        [KeyboardButton(text="📦 Кейс"), KeyboardButton(text="🏆 Топ")],
        [KeyboardButton(text="💼 Профиль"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🎲 Рулетка"), KeyboardButton(text="📜 История покупок")],
        [KeyboardButton(text="ℹ️ Моя скидка")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def shop_keyboard():
    kb = [[KeyboardButton(text=f"⚒️ Купить {p['name']}")] for p in PICKAXES if p["price"] > 0]
    kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def confirm_keyboard():
    kb = [
        [KeyboardButton(text="✅ Подтвердить покупку")],
        [KeyboardButton(text="❌ Отменить покупку")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ================= ОБРАБОТЧИКИ ИГРОКА =================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    user = get_user(user_id)
    if not user:
        create_user(user_id, username)
        await message.answer(
            f"Привет, {username}! Ты стал шахтёром.\n"
            "Копай руду, продавай её, качай уровни и покупай кирки получше!\n"
            "🎁 Бонус — раз в 12 часов.\n"
            "📦 Ежедневный кейс — раз в 24 часа, шанс поймать ДЖЕКПОТ: скидка 50%!\n"
            "🎲 Рулетка откроется с 20 уровня.\n"
            "💰 За каждую покупку кирки — скидка 1% (до 15%)."
        )
    else:
        if user["username"] != username:
            update_user(user_id, username=username)
        pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
        await message.answer(
            f"Снова привет, {username}! Твоя кирка: {pick['name']}, уровень {user['level']}."
        )
    await message.answer("Выбери действие:", reply_markup=main_keyboard())

@dp.message(Command("mine"))
async def cmd_mine(message: Message): await mine_action(message)
@dp.message(Command("profile"))
async def cmd_profile(message: Message): await profile(message)
@dp.message(Command("sell"))
async def cmd_sell(message: Message): await sell_ore(message)
@dp.message(Command("bonus"))
async def cmd_bonus(message: Message): await bonus_action(message)
@dp.message(Command("top"))
async def cmd_top(message: Message): await top_players(message)
@dp.message(Command("shop"))
async def cmd_shop(message: Message): await shop(message)
@dp.message(Command("roulette"))
async def cmd_roulette(message: Message): await roulette_start(message)
@dp.message(Command("history"))
async def cmd_history(message: Message): await purchase_history_cmd(message)
@dp.message(Command("refund"))
async def cmd_refund(message: Message): await refund_last_purchase(message)
@dp.message(Command("discount"))
async def cmd_discount(message: Message): await show_discount(message)
@dp.message(Command("case"))
async def cmd_case(message: Message): await open_case(message)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📜 Список команд:\n"
        "/копать — Добыть руду\n"
        "/профиль — Баланс и рюкзак\n"
        "/продать — Продать руду\n"
        "/бонус — Получить бонус\n"
        "/кейс — Открыть ежедневный кейс\n"
        "/топ — Лучшие игроки\n"
        "/магазин — Магазин кирок\n"
        "/рулетка — Играть в рулетку\n"
        "/история — История покупок кирок\n"
        "/скидка — Твоя текущая скидка\n"
        "/возврат — Вернуть последнюю покупку (15 мин)\n"
        "/команды — Этот список\n"
        "/admin — Админ-панель (только для админов)"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "⛏️ Накопать")
async def mine_action(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.username or str(user_id))
        user = get_user(user_id)

    if not can_mine(user):
        await message.answer(f"Подожди ещё {seconds_until_mine(user)} сек. перед следующей добычей.")
        return

    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    bonus_from_pick = pick["power"] // 10
    bonus_from_level = user["level"] - 1

    stone_count = random.randint(2, 4) + bonus_from_pick + bonus_from_level

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

    update_user(
        user_id,
        ore_stone=user["ore_stone"] + stone_count,
        ore_iron=user["ore_iron"] + iron_count,
        ore_copper=user["ore_copper"] + copper_count,
        ore_gold=user["ore_gold"] + gold_count,
        last_mine_at=datetime.now().isoformat(),
    )
    new_level, levelups = add_xp_and_level_up(user_id, user, total_xp)

    text = "Ты накопал (ушло в рюкзак):\n"
    if stone_count > 0:
        text += f"🪨 Камень × {stone_count}\n"
    if iron_count > 0:
        text += f"⚪ Железная руда × {iron_count}\n"
    if copper_count > 0:
        text += f"🟤 Медная руда × {copper_count}\n"
    if gold_count > 0:
        text += f"🟡 Золотая руда × {gold_count}\n"
    text += f"\n📈 Получено опыта: {total_xp}\n💡 Продай руду через «💰 Продать руду»"
    if levelups > 0:
        text += f"\n🎉 Новый уровень: {new_level}! Теперь руды будет больше."
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "💰 Продать руду")
async def sell_ore(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    prices = get_prices()
    lines = []
    total = 0
    for key in ORE_KEYS:
        count = user[f"ore_{key}"]
        if count > 0:
            money = count * prices.get(key, ORES[key]["price"])
            lines.append(f"{ORES[key]['name']} × {count} = {money} монет")
            total += money

    if total == 0:
        await message.answer("Рюкзак пуст! Сначала накопай руду через «⛏️ Накопать».")
        return

    update_user(
        user_id,
        balance=user["balance"] + total,
        ore_stone=0, ore_iron=0, ore_copper=0, ore_gold=0,
    )
    await message.answer(
        "Продано:\n" + "\n".join(lines) + f"\n\n💰 Итого получено: {total} монет!"
    )

@dp.message(F.text == "🏆 Топ")
async def top_players(message: Message):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, balance, level FROM users ORDER BY balance DESC, level DESC LIMIT 10")
    rich = cur.fetchall()
    cur.execute("SELECT username, level FROM users ORDER BY level DESC, balance DESC LIMIT 10")
    leveled = cur.fetchall()
    conn.close()

    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    lines = ["🏆 ТОП 10 БОГАЧЕЙ:"]
    for i, (username, balance, level) in enumerate(rich):
        lines.append(f"{medals[i]} {username} — {balance} монет (ур. {level})")

    lines.append("\n🏆 ТОП 10 ПО УРОВНЮ:")
    for i, (username, level) in enumerate(leveled):
        lines.append(f"{medals[i]} {username} — уровень {level}")

    await message.answer("\n".join(lines), reply_markup=main_keyboard())

@dp.message(F.text == "🎁 Бонус")
async def bonus_action(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.username or str(user_id))
        user = get_user(user_id)

    if not can_bonus(user):
        hours, minutes = hours_until_bonus(user)
        await message.answer(f"Бонус будет доступен через {hours} ч. {minutes} мин.")
        return

    bonus = get_setting("bonus_amount", BONUS_AMOUNT)
    new_balance = user["balance"] + bonus
    update_user(user_id, balance=new_balance, last_bonus_at=datetime.now().isoformat())
    await message.answer(
        f"🎁 Ты получил бонус: {bonus} монет!\n"
        f"Следующий — через {get_setting('bonus_hours', BONUS_COOLDOWN_HOURS)} часов."
    )

# ================= ЕЖЕДНЕВНЫЙ КЕЙС =================

@dp.message(F.text == "📦 Кейс")
async def open_case(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.username or str(user_id))
        user = get_user(user_id)

    if not can_case(user):
        hours, minutes = hours_until_case(user)
        await message.answer(
            f"📦 Кейс уже открыт! Следующий — через {hours} ч. {minutes} мин."
        )
        return

    update_user(user_id, last_case_at=datetime.now().isoformat())

    opening = await message.answer("📦 Открываем кейс...")
    await asyncio.sleep(1.5)

    roll = random.uniform(0, 100)
    cumulative = 0.0
    reward = CASE_REWARDS[-1]
    for r in CASE_REWARDS:
        cumulative += r["chance"]
        if roll < cumulative:
            reward = r
            break

    user = get_user(user_id)  # свежие данные
    if reward["type"] == "money":
        new_balance = user["balance"] + reward["value"]
        update_user(user_id, balance=new_balance)
        result = f"📦 Из кейса выпало: {reward['name']}!\n💰 Баланс: {new_balance} монет"
    elif reward["type"] == "xp":
        new_level, levelups = add_xp_and_level_up(user_id, user, reward["value"])
        result = f"📦 Из кейса выпало: {reward['name']}!"
        if levelups > 0:
            result += f"\n🎉 Бонусно прокачался до {new_level} уровня!"
    else:  # jackpot
        until = datetime.now() + timedelta(hours=JACKPOT_VALID_HOURS)
        update_user(user_id, jackpot_discount=JACKPOT_DISCOUNT, jackpot_until=until.isoformat())
        result = (
            f"📦 Из кейса выпало: {reward['name']}\n\n"
            f"💥 Твой следующий дроп в магазине будет со скидкой {JACKPOT_DISCOUNT}%!\n"
            f"Действует до: {until.strftime('%d.%m.%Y %H:%M')}\n"
            f"Успей купить кирку в «🛒 Магазине»!"
        )

    result += f"\n\n⏰ Следующий кейс — через {get_setting('case_hours', CASE_COOLDOWN_HOURS)} ч."
    await opening.edit_text(result, reply_markup=main_keyboard())

# ================= РУЛЕТКА =================

@dp.message(F.text == "🎲 Рулетка")
async def roulette_start(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    if user["level"] < ROULETTE_MIN_LEVEL:
        await message.answer(
            f"🔒 Рулетка откроется с {ROULETTE_MIN_LEVEL} уровня.\n"
            f"Твой уровень: {user['level']}. Копай руду!"
        )
        return

    pending_roulette[user_id] = True
    await message.answer(
        f"🎲 Рулетка!\n\n"
        f"Сектора:\n"
        f"• 💥 Джекпот x5 — 2%\n"
        f"• 🔥 Выигрыш x3 — 8%\n"
        f"• ✅ Выигрыш x2 — 20%\n"
        f"• ➖ Возврат ставки — 15%\n"
        f"• ❌ Проигрыш — 55%\n\n"
        f"Ставка: от {ROULETTE_MIN_BET} до {ROULETTE_MAX_BET} монет.\n"
        f"Твой баланс: {user['balance']} монет.\n\n"
        f"Напиши сумму ставки числом, например: 100\n"
        f"Или отправь «отмена», чтобы передумать."
    )

@dp.message(F.text == "отмена")
async def roulette_cancel(message: Message):
    user_id = message.from_user.id
    if pending_roulette.pop(user_id, None):
        await message.answer("Ставка отменена. Возвращаемся к шахтам!")
    else:
        await message.answer("Нечего отменять 🙂")

@dp.message(F.text.regexp(r"^\d+$"))
async def roulette_bet(message: Message):
    user_id = message.from_user.id
    if not pending_roulette.pop(user_id, None):
        return

    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    bet = int(message.text)

    if bet < ROULETTE_MIN_BET or bet > ROULETTE_MAX_BET:
        await message.answer(
            f"Ставка должна быть от {ROULETTE_MIN_BET} до {ROULETTE_MAX_BET} монет. Отправь сумму заново."
        )
        pending_roulette[user_id] = True
        return

    if user["balance"] < bet:
        await message.answer(
            f"Не хватает монет! У тебя {user['balance']}, а нужно {bet}. "
            "Отправь другую сумму или «отмена»."
        )
        pending_roulette[user_id] = True
        return

    now_ts = datetime.now().timestamp()
    last_spin = roulette_cooldowns.get(user_id)
    if last_spin and now_ts - last_spin < ROULETTE_COOLDOWN_SEC:
        remaining = int(ROULETTE_COOLDOWN_SEC - (now_ts - last_spin))
        await message.answer(
            f"🎲 Крути не чаще раза в {ROULETTE_COOLDOWN_SEC} сек. Подожди ещё {remaining} сек."
        )
        pending_roulette[user_id] = True
        return

    spin_msg = await message.answer("🎰 Барабан крутится...")
    await asyncio.sleep(2)

    roll = random.random()
    cumulative = 0.0
    sector = ROULETTE_SECTORS[-1]
    for s in ROULETTE_SECTORS:
        cumulative += s["chance"]
        if roll < cumulative:
            sector = s
            break

    roulette_cooldowns[user_id] = datetime.now().timestamp()

    win = int(bet * sector["mult"])
    delta = win - bet
    new_balance = user["balance"] + delta
    update_user(user_id, balance=new_balance)

    result = f"🎰 Колесо остановилось!\n\n{sector['name']}"
    if delta > 0:
        result += f"\n\nСтавка {bet} → выигрыш {win} монет! Прибыль: +{delta}"
    elif delta == 0:
        result += f"\n\nСтавка {bet} вернулась."
    else:
        result += f"\n\nСтавка {bet} сгорела."
    result += f"\n\n💰 Баланс: {new_balance} монет"

    await spin_msg.edit_text(result, reply_markup=main_keyboard())

# ================= МАГАЗИН: ВЫБОР, ПОДТВЕРЖДЕНИЕ, ОТМЕНА, ВОЗВРАТ =================

@dp.message(F.text == "🛒 Магазин")
async def shop(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    discount, base, jackpot = get_discount(user_id) if user else (0, 0, 0)

    lines = [f"🛒 Магазин кирок (уровень + цена со скидкой {discount}%):"]
    if jackpot > 0:
        until = datetime.fromisoformat(user["jackpot_until"])
        lines.append(f"💥 Активен ДЖЕКПОТ: +{jackpot}% (до {until.strftime('%d.%m.%Y %H:%M')})")
    for p in PICKAXES:
        if p["price"] > 0:
            final_price = p["price"] * (100 - discount) // 100
            lines.append(
                f"• {p['name']} — нужен {p['level']} ур.\n"
                f"  Цена: {p['price']} → со скидкой: {final_price} монет"
            )
    await message.answer("\n".join(lines), reply_markup=shop_keyboard())

@dp.message(F.text.startswith("⚒️ Купить"))
async def buy_pickaxe(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    wanted_name = message.text.replace("⚒️ Купить ", "")
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
            f"Не хватает уровня. Нужен уровень {wanted['level']}, у тебя {user['level']}."
        )
        return

    discount, base, jackpot = get_discount(user_id)
    final_price = wanted["price"] * (100 - discount) // 100

    if user["balance"] < final_price:
        await message.answer(
            f"Недостаточно средств! У тебя {user['balance']} монет, а нужно {final_price} "
            f"(без скидки {wanted['price']})."
        )
        return

    pending_purchase[user_id] = wanted["key"]
    await message.answer(
        f"🧾 Заказ №{wanted_idx} оформлен!\n\n"
        f"Товар: {wanted['name']}\n"
        f"⚡ Мощность: {wanted['power']}\n"
        f"💰 Цена: {wanted['price']} монет\n"
        f"🏷 Скидка: {discount}%"
        + (f" (в т.ч. ДЖЕКПОТ +{jackpot}%)" if jackpot else "") + "\n"
        f"💵 К оплате: {final_price} монет\n"
        f"💼 Твой баланс: {user['balance']} монет\n\n"
        f"Статус: ожидает подтверждения.\n"
        f"Нажми «✅ Подтвердить покупку» или «❌ Отменить покупку».",
        reply_markup=confirm_keyboard()
    )

@dp.message(F.text == "✅ Подтвердить покупку")
async def confirm_purchase(message: Message):
    user_id = message.from_user.id
    pickaxe_key = pending_purchase.pop(user_id, None)
    if not pickaxe_key:
        await message.answer("Нет активного заказа. Загляни в «🛒 Магазин».")
        return

    user = get_user(user_id)
    wanted = PICKAXE_BY_KEY[pickaxe_key]
    discount, base, jackpot = get_discount(user_id)
    final_price = wanted["price"] * (100 - discount) // 100

    # Повторная проверка баланса (мог измениться)
    if user["balance"] < final_price:
        await message.answer(
            f"Недостаточно средств! У тебя {user['balance']}, а нужно {final_price}. Заказ отменён."
        )
        return

    new_balance = user["balance"] - final_price
    update_user(user_id, balance=new_balance, pickaxe_key=wanted["key"])
    add_purchase(user_id, wanted["key"], final_price)

    # Джекпот-скидка сгорает после покупки
    had_jackpot = jackpot > 0
    if had_jackpot:
        consume_jackpot(user_id)

    new_discount, _, _ = get_discount(user_id)
    await message.answer(
        f"✅ Покупка завершена!\n\n"
        f"⛏️ Кирка: {wanted['name']}\n"
        f"💰 Оплачено: {final_price} монет (скидка {discount}%)\n"
        f"📈 Новый баланс: {new_balance} монет\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        f"🏷 Твоя скидка теперь: {new_discount}%"
        + ("\n💥 Джекпот-скидка использована и сгорела." if had_jackpot else "") + "\n"
        f"↩️ Вернуть покупку можно командой /возврат в течение {REFUND_WINDOW_MIN} минут.",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "❌ Отменить покупку")
async def cancel_purchase(message: Message):
    user_id = message.from_user.id
    if pending_purchase.pop(user_id, None):
        await message.answer("❌ Заказ отменён. Деньги не списаны.", reply_markup=main_keyboard())
    else:
        await message.answer("Нет активного заказа для отмены 🙂", reply_markup=main_keyboard())

@dp.message(F.text == "↩️ Вернуть последнюю покупку")
async def refund_last_purchase(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    last = get_last_purchase(user_id)
    if not last:
        await message.answer("У тебя нет покупок для возврата.")
        return

    purchase_id, pickaxe_key, price_paid, timestamp = last

    bought_at = datetime.fromisoformat(timestamp)
    minutes_passed = (datetime.now() - bought_at).total_seconds() / 60
    if minutes_passed > REFUND_WINDOW_MIN:
        await message.answer(
            f"⏰ Время возврата истекло. Вернуть покупку можно только в течение {REFUND_WINDOW_MIN} минут после покупки."
        )
        return

    if user["pickaxe_key"] != pickaxe_key:
        await message.answer("Эту покупку уже нельзя вернуть (кирка больше не текущая).")
        return

    keys = [p["key"] for p in PICKAXES]
    current_idx = keys.index(pickaxe_key)
    if current_idx == 0:
        await message.answer("Это первая кирка — возвращать нечего.")
        return

    prev_key = keys[current_idx - 1]
    new_balance = user["balance"] + price_paid
    update_user(user_id, balance=new_balance, pickaxe_key=prev_key)
    mark_refunded(purchase_id)

    pick_name = PICKAXE_BY_KEY[pickaxe_key]["name"]
    prev_name = PICKAXE_BY_KEY[prev_key]["name"]
    await message.answer(
        f"↩️ Покупка возвращена!\n\n"
        f"⛏️ {pick_name} изъята, вернулась {prev_name}\n"
        f"💰 Возвращено: {price_paid} монет\n"
        f"📈 Новый баланс: {new_balance} монет",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "📜 История покупок")
async def purchase_history_cmd(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    history = get_purchase_history(user_id)
    if not history:
        await message.answer("История покупок пуста. Загляни в «🛒 Магазин»!")
        return

    lines = ["📜 Твои последние покупки:"]
    for pickaxe_key, price, refunded, timestamp in history:
        pick_name = PICKAXE_BY_KEY[pickaxe_key]["name"] if pickaxe_key in PICKAXE_BY_KEY else pickaxe_key
        try:
            ts = datetime.fromisoformat(timestamp).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            ts = timestamp
        status = " (возвращено)" if refunded else ""
        lines.append(f"• {pick_name} — {price} монет ({ts}){status}")

    await message.answer("\n".join(lines), reply_markup=main_keyboard())

@dp.message(F.text == "ℹ️ Моя скидка")
async def show_discount(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    discount, base, jackpot = get_discount(user_id)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM purchase_history WHERE user_id = ? AND refunded = 0", (user_id,))
    purchases_count = cur.fetchone()[0]
    conn.close()

    text = (
        f"🏷 Твоя скидка: {discount}%\n"
        f"• Базовая (за покупки): {base}%\n"
    )
    if jackpot > 0:
        until = datetime.fromisoformat(user["jackpot_until"])
        text += f"• 💥 ДЖЕКПОТ: +{jackpot}% (до {until.strftime('%d.%m.%Y %H:%M')} или до покупки)\n"
    text += (
        f"🛍 Покупок кирок: {purchases_count}\n"
        f"📈 Каждая покупка даёт +{DISCOUNT_PER_PURCHASE}% (максимум {DISCOUNT_MAX}%).\n"
        f"📦 Джекпот-скидку можно выбить из ежедневного кейса «📦 Кейс».\n"
        f"Скидка применяется в «🛒 Магазине» автоматически."
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "💼 Профиль")
async def profile(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return
    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    needed = xp_needed_for_next_level(user["level"])
    backpack = ", ".join(
        f"{ORES[key]['name']} × {user[f'ore_{key}']}"
        for key in ORE_KEYS if user[f"ore_{key}"] > 0
    ) or "пусто"
    discount, base, jackpot = get_discount(user_id)
    text = (
        f"👤 Профиль игрока {user['username']}\n"
        f"💰 Баланс: {user['balance']} монет\n"
        f"📈 Опыт: {user['xp']} / {needed} до уровня {user['level'] + 1}\n"
        f"🏅 Уровень: {user['level']}\n"
        f"⛏️ Твоя кирка: {pick['name']}\n"
        f"🏷 Скидка: {discount}%"
        + (f" (базовая {base}% + джекпот {jackpot}%)" if jackpot else "") + "\n"
        f"🎒 Рюкзак: {backpack}\n"
        f"⏰ Бонус: {'доступен' if can_bonus(user) else 'ещё не скоро'}\n"
        f"📦 Кейс: {'доступен' if can_case(user) else 'уже открыт сегодня'}\n"
        f"🎲 Рулетка: {'открыта' if user['level'] >= ROULETTE_MIN_LEVEL else f'с {ROULETTE_MIN_LEVEL} уровня'}"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: Message):
    await message.answer("Главное меню:", reply_markup=main_keyboard())

# ================= АДМИН-ПАНЕЛЬ =================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет прав администратора!")
        return

    text = (
        "🛠 Админ-панель\n\n"
        "💰 /give <id> <type> <amount> — Выдать игроку (money/xp/ore)\n"
        "🗑 /reset <id> — Сбросить прогресс игрока\n"
        "⚙️ /set_config <key> <value> — Изменить настройки\n"
        "   Ключи: mine_cooldown, bonus_amount, bonus_hours, case_hours\n"
        "💎 /set_price <ore_key> <price> — Изменить цену руды\n"
        "📊 /stats — Общая статистика бота"
    )
    await message.answer(text)

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) != 4:
        await message.answer("❌ Формат: /give <ID_игрока> <тип> <количество>\nТипы: money, xp, ore_stone, ore_iron, ore_copper, ore_gold")
        return

    try:
        target_id = int(args[1])
        item_type = args[2]
        amount = int(args[3])
    except ValueError:
        await message.answer("❌ ID и количество должны быть числами.")
        return

    user = get_user(target_id)
    if not user:
        await message.answer("❌ Игрок не найден в базе.")
        return

    if item_type == "money":
        update_user(target_id, balance=user["balance"] + amount)
        await message.answer(f"✅ Выдано {amount} монет игроку {target_id}")
    elif item_type == "xp":
        update_user(target_id, xp=user["xp"] + amount)
        await message.answer(f"✅ Выдано {amount} опыта игроку {target_id}")
    elif item_type.startswith("ore_"):
        if item_type not in ["ore_stone", "ore_iron", "ore_copper", "ore_gold"]:
            await message.answer("❌ Неверный тип руды.")
            return
        current_val = user[item_type]
        update_user(target_id, **{item_type: current_val + amount})
        await message.answer(f"✅ Выдано {amount} шт. руды игроку {target_id}")
    else:
        await message.answer("❌ Неизвестный тип предмета.")

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Формат: /reset <ID_игрока>")
        return

    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return

    user = get_user(target_id)
    if not user:
        await message.answer("❌ Игрок не найден.")
        return

    update_user(
        target_id,
        balance=0, xp=0, level=1, pickaxe_key="wood",
        ore_stone=0, ore_iron=0, ore_copper=0, ore_gold=0,
        last_mine_at=None, last_bonus_at=None,
        last_case_at=None, jackpot_discount=0, jackpot_until=None
    )
    await message.answer(f"🗑 Прогресс игрока {target_id} сброшен.")

@dp.message(Command("set_config"))
async def cmd_set_config(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) != 3:
        await message.answer("❌ Формат: /set_config <ключ> <значение>\nКлючи: mine_cooldown, bonus_amount, bonus_hours, case_hours")
        return

    key = args[1]
    try:
        value = int(args[2])
    except ValueError:
        await message.answer("❌ Значение должно быть числом.")
        return

    set_setting(key, value)
    await message.answer(f"✅ Настройка '{key}' установлена в {value}")

@dp.message(Command("set_price"))
async def cmd_set_price(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) != 3:
        await message.answer("❌ Формат: /set_price <ore_key> <price>\nКлючи: stone, iron, copper, gold")
        return

    ore_key = args[1]
    try:
        price = int(args[2])
    except ValueError:
        await message.answer("❌ Цена должна быть числом.")
        return

    if ore_key not in ORES:
        await message.answer("❌ Неверная руда.")
        return

    set_ore_price(ore_key, price)
    await message.answer(f"✅ Цена руды '{ore_key}' установлена в {price}")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT SUM(balance) FROM users")
    total_money = cur.fetchone()[0] or 0
    cur.execute("SELECT AVG(level) FROM users")
    avg_level = cur.fetchone()[0] or 0
    conn.close()

    text = (
        "📊 Статистика бота\n\n"
        f"👥 Всего игроков: {total_users}\n"
        f"💰 Всего денег в экономике: {total_money}\n"
        f"🏅 Средний уровень: {avg_level:.2f}"
    )
    await message.answer(text)

# ============ РУССКИЕ КОМАНДЫ ============

@dp.message(Command("копать"))
async def cmd_ru_mine(message: Message): await mine_action(message)
@dp.message(Command("профиль"))
async def cmd_ru_profile(message: Message): await profile(message)
@dp.message(Command("продать"))
async def cmd_ru_sell(message: Message): await sell_ore(message)
@dp.message(Command("бонус"))
async def cmd_ru_bonus(message: Message): await bonus_action(message)
@dp.message(Command("кейс"))
async def cmd_ru_case(message: Message): await open_case(message)
@dp.message(Command("топ"))
async def cmd_ru_top(message: Message): await top_players(message)
@dp.message(Command("магазин"))
async def cmd_ru_shop(message: Message): await shop(message)
@dp.message(Command("рулетка"))
async def cmd_ru_roulette(message: Message): await roulette_start(message)
@dp.message(Command("история"))
async def cmd_ru_history(message: Message): await purchase_history_cmd(message)
@dp.message(Command("скидка"))
async def cmd_ru_discount(message: Message): await show_discount(message)
@dp.message(Command("возврат"))
async def cmd_ru_refund(message: Message): await refund_last_purchase(message)

@dp.message(Command("команды"))
async def cmd_ru_help(message: Message):
    text = (
        "📜 Команды бота:\n"
        "/копать — добыть руду\n"
        "/профиль — баланс и рюкзак\n"
        "/продать — продать руду\n"
        "/бонус — получить бонус\n"
        "/кейс — открыть ежедневный кейс\n"
        "/топ — лучшие игроки\n"
        "/магазин — магазин кирок\n"
        "/рулетка — играть в рулетку\n"
        "/история — история покупок\n"
        "/скидка — твоя скидка\n"
        "/возврат — вернуть последнюю покупку"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(Command("выдать"))
async def cmd_ru_give(message: Message): await cmd_give(message)
@dp.message(Command("сброс"))
async def cmd_ru_reset(message: Message): await cmd_reset(message)
@dp.message(Command("настройка"))
async def cmd_ru_config(message: Message): await cmd_set_config(message)
@dp.message(Command("цена"))
async def cmd_ru_price(message: Message): await cmd_set_price(message)
@dp.message(Command("статистика"))
async def cmd_ru_stats(message: Message): await cmd_stats(message)

# ================= ЗАПУСК =================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
