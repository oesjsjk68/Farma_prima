import asyncio
import os
import random
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta

from aiohttp import web as aio_web
from aiogram import Bot, Dispatcher, F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import hashlib
import hmac
import json
from urllib.parse import parse_qsl

# --- АВТОСБОР ---
AUTO_INTERVAL_HOURS = 3      # шахта собирает ресурсы каждые 3 часа
AUTO_MAX_LEVEL = 10          # максимальный уровень автосбора

def auto_next_price(lvl):
    """Цена следующего уровня: 5000, 10000, 20000, 40000... каждый уровень вдвое дороже."""
    return 5000 * (2 ** lvl)


# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА_ЗДЕСЬ")
if TOKEN == "ВСТАВЬ_ТОКЕН_БОТА_ЗДЕСЬ":
    raise RuntimeError("Не задан BOT_TOKEN! Установи переменную окружения или впиши токен в кавычки.")

# Ссылка на приложение (App). Если задать PANEL_URL, кнопка "Панель" будет
# открывать панель сразу БЕЗ ввода кода — по личной ссылке.
# Пример: https://твой-апп-адрес
PANEL_URL = os.getenv("PANEL_URL", "")

ADMIN_IDS = {5636309834}

bot = Bot(token=TOKEN)
dp = Dispatcher()

MINE_COOLDOWN_SEC = 3
BONUS_AMOUNT = 5000
BONUS_COOLDOWN_HOURS = 12
ROULETTE_COOLDOWN_SEC = 30
ROULETTE_MIN_LEVEL = 20

DISCOUNT_PER_PURCHASE = 1
DISCOUNT_MAX = 15
REFUND_WINDOW_MIN = 15

CASE_COOLDOWN_HOURS = 24
CASE_REWARDS = [
    {"name": "50 монет",    "chance": 2,  "type": "money", "value": 50},
    {"name": "100 монет",   "chance": 25, "type": "money", "value": 100},
    {"name": "500 монет",   "chance": 20, "type": "money", "value": 500},
    {"name": "1000 монет",  "chance": 20, "type": "money", "value": 1000},
    {"name": "5000 монет",  "chance": 10, "type": "money", "value": 5000},
    {"name": "10000 монет", "chance": 4,  "type": "money", "value": 10000},
    {"name": "200 опыта",   "chance": 10, "type": "xp",    "value": 200},
    {"name": "500 опыта",   "chance": 6,  "type": "xp",    "value": 500},
    {"name": "💥 ДЖЕКПОТ: скидка 50% на следующую покупку!", "chance": 3, "type": "jackpot", "value": 50},
]
JACKPOT_DISCOUNT = 50
JACKPOT_VALID_HOURS = 24

ORES = {
    "stone":  {"name": "🪨 Камень",       "price": 2,     "xp": 2},
    "iron":   {"name": "⚪ Железная руда", "price": 8,     "xp": 5},
    "copper": {"name": "🟤 Медная руда",   "price": 20,    "xp": 10},
    "gold":   {"name": "🟡 Золотая руда",  "price": 60000, "xp": 25},
}
ORE_KEYS = ["stone", "iron", "copper", "gold"]

PICKAXES = [
    {"key": "wood",    "name": "🪵 Деревянная", "power": 0,  "price": 0,       "level": 1},
    {"key": "stone",   "name": "⛏️ Каменная",   "power": 3,  "price": 5000,    "level": 10},
    {"key": "iron",    "name": "⛏️ Железная",   "power": 10, "price": 250000,  "level": 20},
    {"key": "gold",    "name": "⛏️ Золотая",    "power": 25, "price": 1000000, "level": 35},
    {"key": "diamond", "name": "⛏️ Алмазная",   "power": 50, "price": 5000000, "level": 50},
]
PICKAXE_BY_KEY = {p["key"]: p for p in PICKAXES}

# ================= ПЕРСОНАЖИ =================
CHARACTERS = [
    {"key": "novice",  "name": "🧒 Новичок",               "bonus": 5,  "chance": 40},
    {"key": "miner",   "name": "👷 Опытный шахтёр",        "bonus": 10, "chance": 25},
    {"key": "digger",  "name": "🧔 Старательный копатель", "bonus": 15, "chance": 15},
    {"key": "geomant", "name": "🔮 Геомант",               "bonus": 20, "chance": 10},
    {"key": "golem",   "name": "🗿 Каменный голем",        "bonus": 30, "chance": 7},
    {"key": "dragon",  "name": "🐉 Огненный дракон",       "bonus": 40, "chance": 3},
]
CHAR_BY_KEY = {c["key"]: c for c in CHARACTERS}
CHAR_DROP_CHANCE = 0.03  # ~3% шанс встретить персонажа за копку


# ================= ЛОКАЦИИ ШАХТ =================
LOCATIONS = [
    {"key": "mine_1", "name": "🪨 Обычная шахта",     "level": 1,  "mult": 1.0, "desc": "базовая добыча"},
    {"key": "mine_2", "name": "🕳 Глубокая шахта",    "level": 15, "mult": 1.5, "desc": "все руды ×1,5"},
    {"key": "mine_3", "name": "🔥 Огненная пропасть", "level": 30, "mult": 2.0, "desc": "все руды ×2,0"},
]
LOCATION_BY_KEY = {l["key"]: l for l in LOCATIONS}

ROULETTE_SECTORS = [
    {"name": "💥 Джекпот x5!",        "chance": 0.02, "mult": 5.0},
    {"name": "🔥 Крупный выигрыш x3", "chance": 0.08, "mult": 3.0},
    {"name": "✅ Выигрыш x2",          "chance": 0.20, "mult": 2.0},
    {"name": "➖ Ставка возвращается", "chance": 0.15, "mult": 1.0},
    {"name": "❌ Проигрыш",            "chance": 0.55, "mult": 0.0},
]
ROULETTE_MIN_BET = 10
ROULETTE_MAX_BET = 100000

# --- АВТОСБОР ---
AUTO_INTERVAL_HOURS = 3      # шахта собирает ресурсы каждые 3 часа
AUTO_MAX_LEVEL = 10          # максимальный уровень автосбора

def auto_next_price(lvl):
    """Цена следующего уровня: 5000, 10000, 20000, 40000... каждый уровень вдвое дороже."""
    return 5000 * (2 ** lvl)

def xp_needed_for_next_level(level):
    return level * 100

# ================= БАЗА ДАННЫХ =================
# ВАЖНО: база хранится в папке data рядом со скриптом — на App эта папка
# не затирается при обновлении/Rebuild, поэтому прогресс игроков НЕ сбрасывается.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "bot_db.sqlite")
db_lock = threading.Lock()

def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with db_lock:
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
                jackpot_until TEXT,
                location_key TEXT DEFAULT 'mine_1'
            )
        """)
        for col, dflt in [
            ("last_bonus_at", None), ("ore_stone", 0), ("ore_iron", 0),
            ("ore_copper", 0), ("ore_gold", 0),
            ("last_case_at", None), ("jackpot_discount", 0), ("jackpot_until", None),
            ("location_key", None),
        ]:
            try:
                if dflt is None:
                    cur.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
                else:
                    cur.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT {dflt}")
            except sqlite3.OperationalError:
                pass
        # Персонажи — заготовка на будущее (выпадение подключим позже)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                user_id INTEGER,
                char_key TEXT,
                PRIMARY KEY (user_id, char_key)
            )
        """)
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
        cur.execute("CREATE TABLE IF NOT EXISTS promos (code TEXT PRIMARY KEY, amount INTEGER, uses INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS promo_users (user_id INTEGER, code TEXT, PRIMARY KEY (user_id, code))")
        # Промокоды: тип награды (money/xp/руда) + автосбор
        try:
            cur.execute("ALTER TABLE promos ADD COLUMN type TEXT DEFAULT 'money'")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE users ADD COLUMN auto_level INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE users ADD COLUMN auto_last_at TEXT")
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
    with db_lock:
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()

def set_ore_price(ore_key, price):
    with db_lock:
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO prices (ore_key, price) VALUES (?, ?)", (ore_key, price))
        conn.commit()
        conn.close()

def add_purchase(user_id, pickaxe_key, price):
    with db_lock:
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
    with db_lock:
        conn = get_conn()
        conn.execute("UPDATE purchase_history SET refunded = 1 WHERE id = ?", (purchase_id,))
        conn.commit()
        conn.close()

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
    d.setdefault("location_key", "mine_1")
    d.setdefault("auto_level", 0)

    return d

def create_user(user_id, username):
    with db_lock:
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
        conn.close()

def update_user(user_id, **kwargs):
    with db_lock:
        fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [user_id]
        conn = get_conn()
        conn.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
        conn.commit()
        conn.close()

def get_discount(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM purchase_history WHERE user_id = ? AND refunded = 0", (user_id,))
    count = cur.fetchone()[0]
    conn.close()
    base = min(DISCOUNT_MAX, count * DISCOUNT_PER_PURCHASE)
    jackpot = 0
    user = get_user(user_id)
    if user and user.get("jackpot_until"):
        try:
            until = datetime.fromisoformat(user["jackpot_until"])
            if datetime.now() <= until:
                jackpot = user.get("jackpot_discount", 0)
        except ValueError:
            pass
    return base + jackpot, base, jackpot

def consume_jackpot(user_id):
    update_user(user_id, jackpot_discount=0, jackpot_until=None)

# ================= ПРОМОКОДЫ (логика: монеты, опыт, руда) =================
PROMO_TYPES = {
    "money": "монет", "xp": "опыта",
    "stone": "🪨 камня", "iron": "⚪ железной руды",
    "copper": "🟤 медной руды", "gold": "🟡 золотой руды",
}

def create_promo(code, ptype, amount, uses):
    with db_lock:
        conn = get_conn()
        conn.execute("INSERT OR REPLACE INTO promos (code, amount, uses, type) VALUES (?, ?, ?, ?)",
                     (code, amount, uses, ptype))
        conn.commit()
        conn.close()

def apply_promo_reward(user_id, ptype, amount):
    if ptype == "money":
        with db_lock:
            conn = get_conn()
            conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            conn.commit()
            conn.close()
    elif ptype == "xp":
        user = get_user(user_id)
        if user:
            add_xp_and_level_up(user_id, user, amount)
    elif ptype in ORE_KEYS:
        with db_lock:
            conn = get_conn()
            conn.execute(f"UPDATE users SET ore_{ptype} = ore_{ptype} + ? WHERE user_id = ?", (amount, user_id))
            conn.commit()
            conn.close()

def redeem_promo(user_id, code):
    code = code.upper()
    with db_lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT amount, uses, type FROM promos WHERE code = ?", (code,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None, f"Промокод «{code}» не найден."
        amount, uses, ptype = row
        ptype = ptype or "money"
        if uses <= 0:
            conn.close()
            return None, f"Промокод «{code}» уже исчерпан."
        cur.execute("SELECT 1 FROM promo_users WHERE user_id = ? AND code = ?", (user_id, code))
        if cur.fetchone():
            conn.close()
            return None, f"Ты уже активировал промокод «{code}»."
        cur.execute("UPDATE promos SET uses = uses - 1 WHERE code = ?", (code,))
        cur.execute("INSERT INTO promo_users (user_id, code) VALUES (?, ?)", (user_id, code))
        conn.commit()
        conn.close()
    apply_promo_reward(user_id, ptype, amount)
    return (ptype, amount), None

# ================= ПЕРСОНАЖИ (логика) =================
def get_user_characters(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT char_key FROM characters WHERE user_id = ?", (user_id,))
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

def add_user_character(user_id, char_key):
    with db_lock:
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO characters (user_id, char_key) VALUES (?, ?)", (user_id, char_key))
        conn.commit()
        conn.close()

def char_bonus_percent(char_keys):
    return sum(CHAR_BY_KEY[c]["bonus"] for c in char_keys if c in CHAR_BY_KEY)

def try_char_drop(user_id):
    if random.random() >= CHAR_DROP_CHANCE:
        return ""
    owned = set(get_user_characters(user_id))
    available = [c for c in CHARACTERS if c["key"] not in owned]
    if not available:
        return ""
    total_w = sum(c["chance"] for c in available)
    r, acc, chosen = random.uniform(0, total_w), 0.0, available[-1]
    for c in available:
        acc += c["chance"]
        if r < acc:
            chosen = c
            break
    add_user_character(user_id, chosen["key"])
    return f"\n🎉 В шахте тебе встретился персонаж: {chosen['name']} (+{chosen['bonus']}% к добыче)! Он присоединился к тебе."

# ================= АВТОСБОР (логика) =================

def perform_auto_mine(user_id):
    user = get_user(user_id)
    if not user:
        return None
    lvl = user.get("auto_level") or 0
    if lvl <= 0:
        return None
    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    stone = random.randint(3, 6) + lvl * 2 + pick["power"] // 10
    iron = random.randint(1, 2) if random.random() < min(0.9, 0.2 + lvl * 0.05 + pick["power"] / 300) else 0
    copper = random.randint(1, 2) if random.random() < min(0.8, 0.1 + lvl * 0.04 + pick["power"] / 500) else 0
    gold = 1 if random.random() < min(0.5, 0.02 + lvl * 0.02 + pick["power"] / 1000) else 0
    total_xp = (stone * ORES["stone"]["xp"] + iron * ORES["iron"]["xp"]
                + copper * ORES["copper"]["xp"] + gold * ORES["gold"]["xp"])
    update_user(user_id,
                ore_stone=user["ore_stone"] + stone,
                ore_iron=user["ore_iron"] + iron,
                ore_copper=user["ore_copper"] + copper,
                ore_gold=user["ore_gold"] + gold,
                auto_last_at=datetime.now().isoformat())
    add_xp_and_level_up(user_id, user, total_xp)
    text = f"🤖 Автосбор (ур. {lvl}) — шахта собрала ресурсы, пока тебя не было:\n"
    if stone: text += f"🪨 Камень × {stone}\n"
    if iron: text += f"⚪ Железная руда × {iron}\n"
    if copper: text += f"🟤 Медная руда × {copper}\n"
    if gold: text += f"🟡 Золотая руда × {gold}\n"
    text += f"\n📈 Опыт: +{total_xp} | Продай через «💰 Продать руду»"
    return text

async def auto_mine_loop():
    """Раз в минуту проверяет, кому пора начислить автосбор, и присылает уведомление."""
    await asyncio.sleep(10)
    while True:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE auto_level > 0")
            ids = [r[0] for r in cur.fetchall()]
            conn.close()
            for uid in ids:
                u = get_user(uid)
                if not u:
                    continue
                last = u.get("auto_last_at")
                if last and datetime.now() < datetime.fromisoformat(last) + timedelta(hours=AUTO_INTERVAL_HOURS):
                    continue
                text = perform_auto_mine(uid)
                if text:
                    try:
                        await bot.send_message(uid, text)
                    except Exception:
                        pass
        except Exception:
            pass
        await asyncio.sleep(60)

# ================= ПЕРЕВОД МОНЕТ (логика) =================
def transfer_coins(from_id, to_id, amount):
    sender = get_user(from_id)
    receiver = get_user(to_id)
    if not receiver:
        return None, "Игрок с таким ID не найден в базе."
    if amount <= 0:
        return None, "Сумма должна быть больше нуля."
    if sender["balance"] < amount:
        return None, f"Не хватает монет: у тебя {sender['balance']}, а нужно {amount}."
    with db_lock:
        conn = get_conn()
        conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, from_id))
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, to_id))
        conn.commit()
        conn.close()
    return amount, None

# ================= СОСТОЯНИЕ =================
pending_roulette = {}
pending_purchase = {}
roulette_cooldowns = {}
admin_pending = {}

LOGIN_CODES = {}          # code -> {user_id, expires_at, used}
CODE_LIFETIME_MINUTES = 15
SESSIONS = {}             # token -> {user_id, expires_at}
SESSION_LIFETIME_HOURS = 12

def generate_login_code(user_id: int) -> str:
    code = str(secrets.randbelow(1_000_000)).zfill(6)
    LOGIN_CODES[code] = {
        "user_id": user_id,
        "expires_at": datetime.now() + timedelta(minutes=CODE_LIFETIME_MINUTES),
        "used": False,
    }
    return code

# ================= КЛАВИАТУРЫ =================
def main_keyboard():
    kb = [
        [KeyboardButton(text="⛏️ Накопать")],
        [KeyboardButton(text="💰 Продать руду"), KeyboardButton(text="🎁 Бонус")],
        [KeyboardButton(text="📦 Кейс"), KeyboardButton(text="🏆 Топ")],
        [KeyboardButton(text="💼 Профиль"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="🎲 Рулетка"), KeyboardButton(text="📜 История покупок")],
        [KeyboardButton(text="ℹ️ Моя скидка"), KeyboardButton(text="↩️ Вернуть покупку")],
        [KeyboardButton(text="🗺 Шахты"), KeyboardButton(text="🧙 Персонажи")],
        [KeyboardButton(text="🤖 Автосбор"), KeyboardButton(text="🎟 Промокод")],
        [KeyboardButton(text="🖥 Панель"), KeyboardButton(text="⚙️ Админ")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def shop_keyboard():
    kb = [[KeyboardButton(text=f"⚒️ Купить {p['name']}")] for p in PICKAXES if p["price"] > 0]
    kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def confirm_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✅ Подтвердить покупку")],
        [KeyboardButton(text="❌ Отменить покупку")],
    ], resize_keyboard=True)

def admin_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Выдать")],
        [KeyboardButton(text="🗑 Сброс игрока"), KeyboardButton(text="⚙️ Настройка")],
        [KeyboardButton(text="💎 Цена руды"), KeyboardButton(text="🔙 Назад")],
    ], resize_keyboard=True)

# ================= ИГРОВАЯ ЛОГИКА (ЯДРО) =================

def can_mine(user):
    if not user["last_mine_at"]:
        return True
    return datetime.now() >= datetime.fromisoformat(user["last_mine_at"]) + timedelta(seconds=get_setting("mine_cooldown", MINE_COOLDOWN_SEC))

def can_bonus(user):
    if not user["last_bonus_at"]:
        return True
    return datetime.now() >= datetime.fromisoformat(user["last_bonus_at"]) + timedelta(hours=get_setting("bonus_hours", BONUS_COOLDOWN_HOURS))

def can_case(user):
    if not user.get("last_case_at"):
        return True
    return datetime.now() >= datetime.fromisoformat(user["last_case_at"]) + timedelta(hours=get_setting("case_hours", CASE_COOLDOWN_HOURS))

def seconds_until_mine(user):
    end = datetime.fromisoformat(user["last_mine_at"]) + timedelta(seconds=get_setting("mine_cooldown", MINE_COOLDOWN_SEC))
    return max(0, int((end - datetime.now()).total_seconds()))

def hours_until_bonus(user):
    end = datetime.fromisoformat(user["last_bonus_at"]) + timedelta(hours=get_setting("bonus_hours", BONUS_COOLDOWN_HOURS))
    total_min = max(0, int((end - datetime.now()).total_seconds() // 60))
    return total_min // 60, total_min % 60

def hours_until_case(user):
    end = datetime.fromisoformat(user["last_case_at"]) + timedelta(hours=get_setting("case_hours", CASE_COOLDOWN_HOURS))
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

def ensure_user(message_or_id, username=None):
    """Возвращает пользователя или создаёт его."""
    if hasattr(message_or_id, "from_user"):
        uid = message_or_id.from_user.id
        username = message_or_id.from_user.username or str(uid)
    else:
        uid = message_or_id
    user = get_user(uid)
    if not user:
        create_user(uid, username)
        user = get_user(uid)
    return user

# --- Ядро: локация ---
def current_location(user):
    loc = LOCATION_BY_KEY.get(user.get("location_key") or "mine_1", LOCATIONS[0])
    if user["level"] < loc["level"]:
        loc = LOCATIONS[0]
    return loc

# --- Ядро: копать (с локациями и персонажами) ---
def perform_mine(user_id):
    user = get_user(user_id)
    if not user:
        create_user(user_id, str(user_id))
        user = get_user(user_id)
    if not can_mine(user):
        return f"Подожди ещё {seconds_until_mine(user)} сек. перед следующей добычей."
    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    loc = current_location(user)
    bonus_pct = char_bonus_percent(get_user_characters(user_id))
    mult = loc["mult"] * (1 + bonus_pct / 100)
    stone_count = int(round((random.randint(2, 4) + pick["power"] // 10 + user["level"] - 1) * mult))
    iron_chance = 0.2 + pick["power"] / 200 + (user["level"] - 1) / 100
    copper_chance = 0.1 + pick["power"] / 400 + (user["level"] - 1) / 200
    gold_chance = 0.05 + pick["power"] / 800 + (user["level"] - 1) / 400
    iron_count = int(round((random.randint(1, 2) if random.random() < iron_chance else 0) * mult))
    copper_count = int(round((random.randint(1, 2) if random.random() < copper_chance else 0) * mult))
    gold_count = int(round((1 if random.random() < gold_chance else 0) * mult))
    total_xp = (stone_count * ORES["stone"]["xp"] + iron_count * ORES["iron"]["xp"]
                + copper_count * ORES["copper"]["xp"] + gold_count * ORES["gold"]["xp"])
    update_user(user_id, ore_stone=user["ore_stone"] + stone_count, ore_iron=user["ore_iron"] + iron_count,
                ore_copper=user["ore_copper"] + copper_count, ore_gold=user["ore_gold"] + gold_count,
                last_mine_at=datetime.now().isoformat())
    new_level, levelups = add_xp_and_level_up(user_id, user, total_xp)
    text = f"⛏️ Локация: {loc['name']}"
    if mult != 1.0:
        text += f" (добыча ×{mult:g})"
    text += "\n\nТы накопал (ушло в рюкзак):\n"
    if stone_count: text += f"🪨 Камень × {stone_count}\n"
    if iron_count:  text += f"⚪ Железная руда × {iron_count}\n"
    if copper_count: text += f"🟤 Медная руда × {copper_count}\n"
    if gold_count:  text += f"🟡 Золотая руда × {gold_count}\n"
    text += f"\n📈 Получено опыта: {total_xp}\n💡 Продай руду через «💰 Продать руду»"
    if levelups > 0:
        text += f"\n🎉 Новый уровень: {new_level}! Теперь руды будет больше."
    text += try_char_drop(user_id)
    return text

# --- Ядро: продать ---
def perform_sell(user_id):
    user = get_user(user_id)
    if not user:
        return "Сначала запусти бота через /start"
    prices = get_prices()
    lines, total = [], 0
    for key in ORE_KEYS:
        count = user[f"ore_{key}"]
        if count > 0:
            money = count * prices.get(key, ORES[key]["price"])
            lines.append(f"{ORES[key]['name']} × {count} = {money} монет")
            total += money
    if total == 0:
        return "Рюкзак пуст! Сначала накопай руду через «⛏️ Накопать»."
    update_user(user_id, balance=user["balance"] + total, ore_stone=0, ore_iron=0, ore_copper=0, ore_gold=0)
    return "Продано:\n" + "\n".join(lines) + f"\n\n💰 Итого получено: {total} монет!"

# --- Ядро: профиль ---
def profile_text(user_id):
    user = get_user(user_id)
    if not user:
        return "Сначала запусти бота через /start"
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
        f"🗺 Локация: {current_location(user)['name']}\n"
        f"🏷 Скидка: {discount}%"
        + (f" (базовая {base}% + джекпот {jackpot}%)" if jackpot else "") + "\n"
        f"🎒 Рюкзак: {backpack}\n"
        f"⏰ Бонус: {'доступен' if can_bonus(user) else 'ещё не скоро'}\n"
        f"📦 Кейс: {'доступен' if can_case(user) else 'уже открыт сегодня'}\n"
        f"🎲 Рулетка: {'открыта' if user['level'] >= ROULETTE_MIN_LEVEL else f'с {ROULETTE_MIN_LEVEL} уровня'}"
    )
    return text

# ================= HTML ДЛЯ ПАНЕЛИ =================

def inventory_html(user):
    prices = get_prices()
    rows, total = [], 0
    for key in ORE_KEYS:
        count = user[f"ore_{key}"]
        price = prices.get(key, ORES[key]["price"])
        cost = count * price
        total += cost
        rows.append(f"<tr><td>{ORES[key]['name']}</td><td>{count}</td><td>{price}</td><td>{cost}</td></tr>")
    if not rows:
        return '<div class="card"><p>🎒 Рюкзак пуст — сходи копать ⛏️</p></div>'
    return (
        '<div class="card"><table>'
        "<tr><th>Руда</th><th>Кол-во</th><th>Цена</th><th>Итого</th></tr>"
        + "".join(rows)
        + f'</table><p class="sum">💰 Всё это стоит {total} монет</p></div>'
    )

def index_html():
    ores = "".join(
        f"<tr><td>{o['name']}</td><td>{o['price']}</td><td>{o['xp']} опыта</td></tr>"
        for o in ORES.values()
    )
    picks = "".join(
        f"<tr><td>{p['name']}</td><td>{p['power']}</td><td>{p['price'] if p['price'] else '—'}</td><td>ур. {p['level']}</td></tr>"
        for p in PICKAXES
    )
    return (
        '<div class="card"><h3>💎 Руды</h3><table>'
        "<tr><th>Руда</th><th>Цена</th><th>Опыт</th></tr>"
        + ores + "</table></div>"
        '<div class="card"><h3>⛏️ Кирки</h3><table>'
        "<tr><th>Кирка</th><th>Мощность</th><th>Цена</th><th>Уровень</th></tr>"
        + picks + "</table></div>"
        '<div class="card"><h3>🧙 Персонажи</h3><p>Раздел в разработке — тут появятся персонажи шахт.</p></div>'
    )

# ================= ХЕНДЛЕРЫ ИГРОКА =================

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
            "💰 За каждую покупку кирки — скидка 1% (до 15%).\n"
            "🖥 Кнопка «Панель» — вход в веб-панель без кода."
        )
    else:
        if user["username"] != username:
            update_user(user_id, username=username)
        pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
        await message.answer(f"Снова привет, {username}! Твоя кирка: {pick['name']}, уровень {user['level']}.")
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

@dp.message(Command("б"))
async def cmd_short_balance(message: Message):
    await message.answer(profile_text(message.from_user.id), reply_markup=main_keyboard())

@dp.message(Command("бо"))
async def cmd_short_bonus(message: Message):
    await bonus_action(message)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📜 Список команд:\n"
        "/копать — Добыть руду\n"
        "/профиль — Баланс и рюкзак (коротко: /б)\n"
        "/продать — Продать руду\n"
        "/бонус — Получить бонус (коротко: /бо)\n"
        "/кейс — Открыть ежедневный кейс\n"
        "/топ — Лучшие игроки\n"
        "/магазин — Магазин кирок\n"
        "/рулетка — Играть в рулетку\n"
        "/история — История покупок кирок\n"
        "/скидка — Твоя текущая скидка\n"
        "/возврат — Вернуть последнюю покупку (15 мин)\n"
        "/промокод — Активировать промокод\n"
        "/передать — Перевести монеты игроку\n"
        "/panel — Вход в веб-панель (ссылка без кода)\n"
        "/команды — Этот список\n"
        "/admin — Админ-панель (только для админов)"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(Command("промокод"))
async def cmd_promo(message: Message):
    args = message.text.split()
    if len(args) == 1:
        await message.answer(
            "🎟 Активировать промокод:\n/промокод <код>\n\n"
            "Админам — создать:\n/промокод создать <КОД> <тип> <количество> <активаций>\n"
            "Типы: money, xp, stone, iron, copper, gold\n"
            "Например: /промокод создать SHAHTA2026 iron 15 10")
        return
    if args[1].lower() in ("создать", "create"):
        if not is_admin(message.from_user.id):
            return
        if len(args) == 5 and args[3].isdigit() and args[4].isdigit():
            code, ptype, amount, uses = args[2].upper(), "money", int(args[3]), int(args[4])
        elif len(args) == 6 and args[4].isdigit() and args[5].isdigit():
            code, ptype, amount, uses = args[2].upper(), args[3].lower(), int(args[4]), int(args[5])
        else:
            await message.answer("❌ Формат: /промокод создать <КОД> <тип> <количество> <активаций>")
            return
        if ptype not in PROMO_TYPES:
            await message.answer("❌ Тип: money, xp, stone, iron, copper, gold")
            return
        create_promo(code, ptype, amount, uses)
        await message.answer(f"✅ Промокод «{code}» создан: {amount} {PROMO_TYPES[ptype]}, {uses} активаций.")
        return
    user_id = message.from_user.id
    ensure_user(message)
    reward, err = redeem_promo(user_id, args[1])
    if err:
        await message.answer(f"❌ {err}")
    else:
        ptype, amount = reward
        await message.answer(f"🎉 Промокод активирован! +{amount} {PROMO_TYPES[ptype]}")

# ================= ПЕРЕВОД МОНЕТ (хендлер) =================
@dp.message(Command("передать"))
async def cmd_transfer(message: Message):
    args = message.text.split()
    if len(args) != 3:
        await message.answer("💸 Перевод монет игроку:\n/передать <ID_игрока> <сумма>\nНапример: /передать 123456789 500")
        return
    if not args[1].isdigit() or not args[2].isdigit():
        await message.answer("❌ ID и сумма должны быть числами.")
        return
    target_id, amount = int(args[1]), int(args[2])
    if target_id == message.from_user.id:
        await message.answer("🪞 Сам себе перевёл — сам себе потратил. Нужен чужой ID!")
        return
    ensure_user(message)
    transferred, err = transfer_coins(message.from_user.id, target_id, amount)
    if err:
        await message.answer(f"❌ {err}")
    else:
        me = get_user(message.from_user.id)
        await message.answer(
            f"💸 Перевод выполнен!\n"
            f"{transferred} монет ушли игроку {target_id}.\n"
            f"💰 Твой баланс: {me['balance']} монет"
        )

@dp.message(F.text == "⛏️ Накопать")
async def mine_action(message: Message):
    await message.answer(perform_mine(message.from_user.id), reply_markup=main_keyboard())

@dp.message(F.text == "💰 Продать руду")
async def sell_ore(message: Message):
    await message.answer(perform_sell(message.from_user.id), reply_markup=main_keyboard())

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
    user = ensure_user(message)
    if not can_bonus(user):
        hours, minutes = hours_until_bonus(user)
        await message.answer(f"Бонус будет доступен через {hours} ч. {minutes} мин.")
        return
    bonus = get_setting("bonus_amount", BONUS_AMOUNT)
    update_user(user_id, balance=user["balance"] + bonus, last_bonus_at=datetime.now().isoformat())
    await message.answer(
        f"🎁 Ты получил бонус: {bonus} монет!\n"
        f"Следующий — через {get_setting('bonus_hours', BONUS_COOLDOWN_HOURS)} часов."
    )

# ================= ЕЖЕДНЕВНЫЙ КЕЙС =================

@dp.message(F.text == "📦 Кейс")
async def open_case(message: Message):
    user_id = message.from_user.id
    user = ensure_user(message)
    if not can_case(user):
        hours, minutes = hours_until_case(user)
        await message.answer(f"📦 Кейс уже открыт! Следующий — через {hours} ч. {minutes} мин.")
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

    user = get_user(user_id)
    if reward["type"] == "money":
        new_balance = user["balance"] + reward["value"]
        update_user(user_id, balance=new_balance)
        result = f"📦 Из кейса выпало: {reward['name']}!\n💰 Баланс: {new_balance} монет"
    elif reward["type"] == "xp":
        new_level, levelups = add_xp_and_level_up(user_id, user, reward["value"])
        result = f"📦 Из кейса выпало: {reward['name']}!"
        if levelups > 0:
            result += f"\n🎉 Бонусно прокачался до {new_level} уровня!"
    else:
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
            f"🔒 Рулетка откроется с {ROULETTE_MIN_LEVEL} уровня.\nТвой уровень: {user['level']}. Копай руду!"
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
    if pending_roulette.pop(message.from_user.id, None):
        await message.answer("Ставка отменена. Возвращаемся к шахтам!")
    else:
        raise SkipHandler  # не наш случай — пусть обрабатывают другие хендлеры

@dp.message(F.text.regexp(r"^\d+$"))
async def roulette_bet(message: Message):
    user_id = message.from_user.id
    if not pending_roulette.pop(user_id, None):
        raise SkipHandler  # это не ставка — пусть идёт дальше (в т.ч. в админ-диалог)

    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    bet = int(message.text)
    if bet < ROULETTE_MIN_BET or bet > ROULETTE_MAX_BET:
        pending_roulette[user_id] = True
        await message.answer(f"Ставка должна быть от {ROULETTE_MIN_BET} до {ROULETTE_MAX_BET} монет. Отправь сумму заново.")
        return
    if user["balance"] < bet:
        pending_roulette[user_id] = True
        await message.answer(f"Не хватает монет! У тебя {user['balance']}, а нужно {bet}. Отправь другую сумму или «отмена».")
        return

    now_ts = datetime.now().timestamp()
    last_spin = roulette_cooldowns.get(user_id)
    if last_spin and now_ts - last_spin < ROULETTE_COOLDOWN_SEC:
        remaining = int(ROULETTE_COOLDOWN_SEC - (now_ts - last_spin))
        pending_roulette[user_id] = True
        await message.answer(f"🎲 Крути не чаще раза в {ROULETTE_COOLDOWN_SEC} сек. Подожди ещё {remaining} сек.")
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

# ================= МАГАЗИН =================

@dp.message(F.text == "🛒 Магазин")
async def shop(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    discount, base, jackpot = get_discount(user_id) if user else (0, 0, 0)
    lines = [f"🛒 Магазин кирок (уровень + цена со скидкой {discount}%):"]
    if user and jackpot > 0:
        until = datetime.fromisoformat(user["jackpot_until"])
        lines.append(f"💥 Активен ДЖЕКПОТ: +{jackpot}% (до {until.strftime('%d.%m.%Y %H:%M')})")
    for p in PICKAXES:
        if p["price"] > 0:
            final_price = p["price"] * (100 - discount) // 100
            lines.append(f"• {p['name']} — нужен {p['level']} ур.\n  Цена: {p['price']} → со скидкой: {final_price} монет")
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
    current_idx, wanted_idx = keys.index(current_pick["key"]), keys.index(wanted["key"])
    if wanted_idx != current_idx + 1:
        await message.answer("Покупай по порядку: сначала каменную, потом железную и т.д.")
        return
    if user["level"] < wanted["level"]:
        await message.answer(f"Не хватает уровня. Нужен уровень {wanted['level']}, у тебя {user['level']}.")
        return
    discount, base, jackpot = get_discount(user_id)
    final_price = wanted["price"] * (100 - discount) // 100
    if user["balance"] < final_price:
        await message.answer(f"Недостаточно средств! У тебя {user['balance']} монет, а нужно {final_price} (без скидки {wanted['price']}).")
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
    if user["balance"] < final_price:
        await message.answer(f"Недостаточно средств! У тебя {user['balance']}, а нужно {final_price}. Заказ отменён.")
        return
    new_balance = user["balance"] - final_price
    update_user(user_id, balance=new_balance, pickaxe_key=wanted["key"])
    add_purchase(user_id, wanted["key"], final_price)
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
    if pending_purchase.pop(message.from_user.id, None):
        await message.answer("❌ Заказ отменён. Деньги не списаны.", reply_markup=main_keyboard())
    else:
        await message.answer("Нет активного заказа для отмены 🙂", reply_markup=main_keyboard())

@dp.message(F.text == "↩️ Вернуть покупку")
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
    if (datetime.now() - bought_at).total_seconds() / 60 > REFUND_WINDOW_MIN:
        await message.answer(f"⏰ Время возврата истекло. Вернуть покупку можно только в течение {REFUND_WINDOW_MIN} минут после покупки.")
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
    await message.answer(
        f"↩️ Покупка возвращена!\n\n"
        f"⛏️ {PICKAXE_BY_KEY[pickaxe_key]['name']} изъята, вернулась {PICKAXE_BY_KEY[prev_key]['name']}\n"
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
    text = f"🏷 Твоя скидка: {discount}%\n• Базовая (за покупки): {base}%\n"
    if jackpot > 0:
        until = datetime.fromisoformat(user["jackpot_until"])
        text += f"• 💥 ДЖЕКПОТ: +{jackpot}% (до {until.strftime('%d.%m.%Y %H:%M')} или до покупки)\n"
    text += (
        f"📈 Каждая покупка даёт +{DISCOUNT_PER_PURCHASE}% (максимум {DISCOUNT_MAX}%).\n"
        f"📦 Джекпот-скидку можно выбить из ежедневного кейса «📦 Кейс».\n"
        f"Скидка применяется в «🛒 Магазине» автоматически."
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "💼 Профиль")
async def profile(message: Message):
    await message.answer(profile_text(message.from_user.id), reply_markup=main_keyboard())

# ================= ЛОКАЦИИ (хендлеры) =================
@dp.message(Command("шахты"))
@dp.message(F.text == "🗺 Шахты")
async def mines_handler(message: Message):
    user = ensure_user(message)
    cur_key = user.get("location_key") or "mine_1"
    lines = ["🗺 Локации шахт:\n"]
    for loc in LOCATIONS:
        if user["level"] >= loc["level"]:
            mark = "📍 " if loc["key"] == cur_key else "• "
            lines.append(f"{mark}{loc['name']} — {loc['desc']}")
        else:
            lines.append(f"🔒 {loc['name']} — откроется с {loc['level']} уровня")
    kb_rows = [[KeyboardButton(text=f"➡️ Сменить: {loc['name']}")]
               for loc in LOCATIONS if user["level"] >= loc["level"] and loc["key"] != cur_key]
    kb_rows.append([KeyboardButton(text="🔙 Назад")])
    await message.answer("\n".join(lines), reply_markup=ReplyKeyboardMarkup(keyboard=kb_rows, resize_keyboard=True))

@dp.message(F.text.startswith("➡️ Сменить: "))
async def switch_location(message: Message):
    user = ensure_user(message)
    loc = next((l for l in LOCATIONS if l["name"] == message.text.replace("➡️ Сменить: ", "")), None)
    if not loc:
        return
    if user["level"] < loc["level"]:
        await message.answer(f"🔒 «{loc['name']}» откроется с {loc['level']} уровня.", reply_markup=main_keyboard())
        return
    update_user(user["user_id"], location_key=loc["key"])
    await message.answer(f"✅ Ты перешёл в {loc['name']}! Бонус: {loc['desc']}. Копай — руды теперь больше!",
                         reply_markup=main_keyboard())

# ================= ПЕРСОНАЖИ (хендлер) =================
@dp.message(Command("персонажи"))
@dp.message(F.text == "🧙 Персонажи")
async def characters_handler(message: Message):
    user = ensure_user(message)
    owned = get_user_characters(user["user_id"])
    if not owned:
        await message.answer("🧙 У тебя пока нет персонажей.\nКопай руду — с шансом ~3% за копку можно встретить персонажа, он даст постоянный бонус к добыче!", reply_markup=main_keyboard())
        return
    lines = ["🧙 Твои персонажи:"]
    for key in owned:
        c = CHAR_BY_KEY[key]
        lines.append(f"• {c['name']} — +{c['bonus']}% к добыче")
    lines.append(f"\n💪 Суммарный бонус: +{char_bonus_percent(owned)}% к добыче руды")
    await message.answer("\n".join(lines), reply_markup=main_keyboard())

# ================= АВТОСБОР (хендлеры) =================

@dp.message(F.text == "🤖 Автосбор")
async def auto_handler(message: Message):
    user = ensure_user(message)
    lvl = user.get("auto_level") or 0
    if lvl <= 0:
        price = auto_next_price(0)
        await message.answer(
            f"🤖 Автосбор — шахта работает сама!\n"
            f"Каждые {AUTO_INTERVAL_HOURS} часа бот сам накопает руду и пришлёт тебе уведомление.\n\n"
            f"💳 Уровень 1 стоит {price} монет.\n"
            f"💰 Твой баланс: {user['balance']} монет.\n"
            f"⬆️ Жми кнопку ниже, чтобы купить.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="⬆️ Улучшить автосбор")], [KeyboardButton(text="🔙 Назад")]],
                resize_keyboard=True))
        return
    mins_left = 0
    if user.get("auto_last_at"):
        end = datetime.fromisoformat(user["auto_last_at"]) + timedelta(hours=AUTO_INTERVAL_HOURS)
        mins_left = max(0, int((end - datetime.now()).total_seconds() // 60))
    price = auto_next_price(lvl) if lvl < AUTO_MAX_LEVEL else None
    text = (f"🤖 Автосбор: уровень {lvl}\n"
            f"⏳ Следующий сбор: {'прямо сейчас' if mins_left == 0 else f'через {mins_left // 60} ч. {mins_left % 60} мин.'}\n"
            f"Больше уровень — больше руды за цикл.\n")
    if price:
        text += f"\n⬆️ Улучшение до ур. {lvl + 1}: {price} монет (баланс: {user['balance']})"
    else:
        text += "\n🏆 Это максимальный уровень!"
    await message.answer(text, reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬆️ Улучшить автосбор")], [KeyboardButton(text="🔙 Назад")]],
        resize_keyboard=True))

@dp.message(F.text == "⬆️ Улучшить автосбор")
async def auto_upgrade(message: Message):
    user = ensure_user(message)
    lvl = user.get("auto_level") or 0
    if lvl >= AUTO_MAX_LEVEL:
        await message.answer("🤖 У тебя максимальный уровень автосбора!", reply_markup=main_keyboard())
        return
    price = auto_next_price(lvl)
    if user["balance"] < price:
        await message.answer(f"❌ Не хватает монет: нужно {price}, у тебя {user['balance']}.")
        return
    kwargs = {"balance": user["balance"] - price, "auto_level": lvl + 1}
    if lvl == 0:
        kwargs["auto_last_at"] = datetime.now().isoformat()
    update_user(message.from_user.id, **kwargs)
    await message.answer(
        f"✅ Автосбор прокачан до уровня {lvl + 1}!\n"
        f"Шахта теперь добывает больше, сбор каждые {AUTO_INTERVAL_HOURS} часа.\n"
        f"Следующее улучшение: {auto_next_price(lvl + 1)} монет.",
        reply_markup=main_keyboard())

@dp.message(F.text == "🎟 Промокод")
async def promo_button(message: Message):
    await message.answer("🎟 Напиши промокод так:\n/промокод ТВОЙКОД")

# ================= ПАНЕЛЬ: ВХОД БЕЗ КОДА (И ПО КОДУ — ЗАПАСНОЙ) =================

@dp.message(Command("panel"))
@dp.message(F.text == "🖥 Панель")
async def panel_cmd(message: Message):
    ensure_user(message)
    if PANEL_URL:
        # Вход без кода: сразу выдаём личную ссылку с токеном сессии
        token = secrets.token_hex(16)
        SESSIONS[token] = {
            "user_id": message.from_user.id,
            "expires_at": datetime.now() + timedelta(hours=SESSION_LIFETIME_HOURS),
        }
        url = PANEL_URL.rstrip("/") + "/panel?token=" + token
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть панель", url=url)]
        ])
        await message.answer(
            "🖥 Панель готова! Жми кнопку — откроется твой профиль без всяких кодов.\n"
            "Ссылка действует 12 часов, никому её не пересылай.",
            reply_markup=kb
        )
    else:
        # Запасной вариант: если PANEL_URL не задан — вход по коду
        code = generate_login_code(message.from_user.id)
        await message.answer(
            f"🔐 Код для входа в веб-панель: <b>{code}</b>\n\n"
            f"⏳ Действует {CODE_LIFETIME_MINUTES} минут, одноразовый.\n"
            f"🌐 Введи его на странице панели.\n\n"
            f"💡 Совет: задай переменную PANEL_URL на App — тогда панель будет открываться сразу по кнопке, без кода.",
            parse_mode="HTML"
        )

@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: Message):
    admin_pending.pop(message.from_user.id, None)
    await message.answer("Главное меню:", reply_markup=main_keyboard())

# ================= АДМИН-ПАНЕЛЬ =================

@dp.message(Command("admin"))
@dp.message(F.text == "⚙️ Админ")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет прав администратора!")
        return
    await message.answer("🛠 Админ-панель. Выбирай действие кнопкой — бот всё спросит сам:", reply_markup=admin_keyboard())

@dp.message(Command("give"))
async def cmd_give(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 4:
        await message.answer("❌ Формат: /give <ID_игрока> <тип> <количество>\nТипы: money, xp, ore_stone, ore_iron, ore_copper, ore_gold")
        return
    try:
        target_id, amount = int(args[1]), int(args[3])
        item_type = args[2]
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
    elif item_type in ("ore_stone", "ore_iron", "ore_copper", "ore_gold"):
        update_user(target_id, **{item_type: user[item_type] + amount})
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
    if not get_user(target_id):
        await message.answer("❌ Игрок не найден.")
        return
    update_user(target_id, balance=0, xp=0, level=1, pickaxe_key="wood",
                ore_stone=0, ore_iron=0, ore_copper=0, ore_gold=0,
                last_mine_at=None, last_bonus_at=None,
                last_case_at=None, jackpot_discount=0, jackpot_until=None,
                location_key="mine_1")
    await message.answer(f"🗑 Прогресс игрока {target_id} сброшен.")

@dp.message(Command("set_config"))
async def cmd_set_config(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("❌ Формат: /set_config <ключ> <значение>\nКлючи: mine_cooldown, bonus_amount, bonus_hours, case_hours")
        return
    try:
        value = int(args[2])
    except ValueError:
        await message.answer("❌ Значение должно быть числом.")
        return
    set_setting(args[1], value)
    await message.answer(f"✅ Настройка '{args[1]}' установлена в {value}")

@dp.message(Command("set_price"))
async def cmd_set_price(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("❌ Формат: /set_price <ore_key> <price>\nКлючи: stone, iron, copper, gold")
        return
    try:
        price = int(args[2])
    except ValueError:
        await message.answer("❌ Цена должна быть числом.")
        return
    if args[1] not in ORES:
        await message.answer("❌ Неверная руда.")
        return
    set_ore_price(args[1], price)
    await message.answer(f"✅ Цена руды '{args[1]}' установлена в {price}")

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
    await message.answer(
        "📊 Статистика бота\n\n"
        f"👥 Всего игроков: {total_users}\n"
        f"💰 Всего денег в экономике: {total_money}\n"
        f"🏅 Средний уровень: {avg_level:.2f}"
    )

@dp.message(F.text == "📊 Статистика")
async def adm_stats_btn(message: Message):
    if is_admin(message.from_user.id):
        await cmd_stats(message)

@dp.message(F.text == "👥 Выдать")
async def adm_give_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    admin_pending[message.from_user.id] = {"step": "give_id"}
    await message.answer("👥 Напиши ID игрока, которому выдать (число).")

@dp.message(F.text == "🗑 Сброс игрока")
async def adm_reset_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    admin_pending[message.from_user.id] = {"step": "reset_id"}
    await message.answer("🗑 Напиши ID игрока, которого сбросить.")

@dp.message(F.text == "⚙️ Настройка")
async def adm_config_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    admin_pending[message.from_user.id] = {"step": "cfg_key"}
    await message.answer("⚙️ Напиши ключ настройки:\nmine_cooldown, bonus_amount, bonus_hours, case_hours")

@dp.message(F.text == "💎 Цена руды")
async def adm_price_start(message: Message):
    if not is_admin(message.from_user.id):
        return
    admin_pending[message.from_user.id] = {"step": "price_ore"}
    await message.answer("💎 Напиши руду: stone, iron, copper или gold")

@dp.message(F.text)
async def admin_steps(message: Message):
    state = admin_pending.get(message.from_user.id)
    if not state:
        raise SkipHandler  # нет активного диалога — пусть обрабатывает запасной хендлер
    text = message.text.strip()
    if text in ("🔙 Назад", "отмена"):
        admin_pending.pop(message.from_user.id, None)
        await message.answer("Действие отменено.", reply_markup=main_keyboard())
        return
    step = state["step"]

    if step == "give_id":
        if not text.isdigit():
            await message.answer("❌ ID должен быть числом. Напиши заново или «отмена».")
            return
        state["give_id"] = int(text)
        state["step"] = "give_type"
        await message.answer("Что выдать? Напиши одно из: money, xp, level, auto, ore_stone, ore_iron, ore_copper, ore_gold")
        return

    if step == "give_type":
        types = ("money", "xp", "level", "auto", "ore_stone", "ore_iron", "ore_copper", "ore_gold")
        if text not in types:
            await message.answer("❌ Напиши одно из: money, xp, level, auto, ore_stone, ore_iron, ore_copper, ore_gold")
            return
        state["give_type"] = text
        state["step"] = "give_amount"
        await message.answer("Теперь напиши количество (число). Для level и auto это уровень.")
        return

    if step == "give_amount":
        if not text.isdigit():
            await message.answer("❌ Количество должно быть числом. Напиши заново.")
            return
        target_id, item_type, amount = state["give_id"], state["give_type"], int(text)
        user = get_user(target_id)
        if not user:
            admin_pending.pop(message.from_user.id, None)
            await message.answer("❌ Игрок не найден в базе.")
            return
        if item_type == "money":
            update_user(target_id, balance=user["balance"] + amount)
        elif item_type == "xp":
            update_user(target_id, xp=user["xp"] + amount)
        elif item_type == "level":
            update_user(target_id, level=max(1, amount))
        elif item_type == "auto":
            update_user(target_id, auto_level=max(user.get("auto_level") or 0, amount))
        else:
            update_user(target_id, **{item_type: user[item_type] + amount})
        admin_pending.pop(message.from_user.id, None)
        await message.answer(f"✅ Готово! Игроку {target_id} выдано: {amount} ({item_type}).", reply_markup=admin_keyboard())
        return

    if step == "reset_id":
        if not text.isdigit():
            await message.answer("❌ ID должен быть числом. Напиши заново или «отмена».")
            return
        target_id = int(text)
        if not get_user(target_id):
            admin_pending.pop(message.from_user.id, None)
            await message.answer("❌ Игрок не найден.")
            return
        update_user(target_id, balance=0, xp=0, level=1, pickaxe_key="wood",
                    ore_stone=0, ore_iron=0, ore_copper=0, ore_gold=0,
                    last_mine_at=None, last_bonus_at=None,
                    last_case_at=None, jackpot_discount=0, jackpot_until=None,
                    location_key="mine_1")
        admin_pending.pop(message.from_user.id, None)
        await message.answer(f"🗑 Прогресс игрока {target_id} сброшен.", reply_markup=admin_keyboard())
        return

    if step == "cfg_key":
        if text not in ("mine_cooldown", "bonus_amount", "bonus_hours", "case_hours"):
            await message.answer("❌ Напиши один из ключей: mine_cooldown, bonus_amount, bonus_hours, case_hours")
            return
        state["cfg_key"] = text
        state["step"] = "cfg_value"
        await message.answer("Теперь напиши новое значение (число).")
        return

    if step == "cfg_value":
        if not text.isdigit():
            await message.answer("❌ Значение должно быть числом. Напиши заново.")
            return
        set_setting(state["cfg_key"], int(text))
        admin_pending.pop(message.from_user.id, None)
        await message.answer(f"✅ Настройка «{state['cfg_key']}» = {text}", reply_markup=admin_keyboard())
        return

    if step == "price_ore":
        if text not in ORES:
            await message.answer("❌ Напиши: stone, iron, copper или gold")
            return
        state["ore"] = text
        state["step"] = "price_value"
        await message.answer(f"Теперь напиши новую цену руды «{text}» (число).")
        return

    if step == "price_value":
        if not text.isdigit():
            await message.answer("❌ Цена должна быть числом. Напиши заново.")
            return
        set_ore_price(state["ore"], int(text))
        admin_pending.pop(message.from_user.id, None)
        await message.answer(f"✅ Цена «{state['ore']}» = {text} монет", reply_markup=admin_keyboard())
        return

# ================= РУССКИЕ КОМАНДЫ (СЛЭШ) =================

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
@dp.message(Command("передать2"))
async def cmd_ru_transfer2(message: Message): await cmd_transfer(message)
@dp.message(Command("промокод2"))
async def cmd_ru_promo2(message: Message): await cmd_promo(message)

@dp.message(Command("команды"))
async def cmd_ru_help(message: Message): await cmd_help(message)

# ================= ЗАПАСНОЙ ТЕКСТОВЫЙ ХЕНДЛЕР (САМЫЙ ПОСЛЕДНИЙ) =================

@dp.message(F.text)
async def text_commands(message: Message):
    text = message.text.strip().lower()
    commands = {
        "копать": mine_action,
        "профиль": profile,
        "продать": sell_ore,
        "бонус": bonus_action,
        "кейс": open_case,
        "топ": top_players,
        "магазин": shop,
        "рулетка": roulette_start,
        "история": purchase_history_cmd,
        "скидка": show_discount,
        "возврат": refund_last_purchase,
        "команды": cmd_help,
        "админ": admin_panel,
        "панель": panel_cmd,
        "автосбор": auto_handler,
        "авто": auto_handler,
        "промокод": cmd_promo,
        "шахты": mines_handler,
        "персонажи": characters_handler,
    }
    handler = commands.get(text)
    if handler:
        await handler(message)
    else:
        await message.answer(
            "Не понял 🤔 Нажми кнопку на клавиатуре или напиши:\n"
            "копать, продать, профиль, бонус, кейс, топ, магазин, рулетка, панель"
        )

# ================= ВЕБ-ПАНЕЛЬ (AIOHTTP, БЕЗ ДОП. УСТАНОВОК) =================

LOGIN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Вход в панель</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>body{font-family:sans-serif;background:#1a1a2e;color:#eee;display:flex;justify-content:center;padding-top:60px}
.card{background:#16213e;padding:30px;border-radius:12px;text-align:center}
input{padding:10px;font-size:18px;border-radius:6px;border:none;text-align:center;width:160px}
button{padding:10px 24px;font-size:16px;background:#0088cc;color:#fff;border:none;border-radius:6px;cursor:pointer;margin-top:12px}
.err{color:#ff6b6b;margin-top:10px;min-height:20px}</style></head>
<body><div class="card"><h1>🖥 Панель шахтёра</h1>
<form onsubmit="return doLogin()"><input id="code" placeholder="Код из бота" maxlength="6" inputmode="numeric"><br>
<button>Войти</button></form><div id="msg" class="err"></div></div>
<script>async function doLogin(){e=window.event;e.preventDefault();
const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:document.getElementById('code').value.trim()})});
const d=await r.json();if(d.ok){location.href='/panel?token='+d.token}else{document.getElementById('msg').innerText=d.message||'Ошибка'}return false}
window.addEventListener('load',async()=>{
  const tg=window.Telegram&&window.Telegram.WebApp;
  if(tg&&tg.initData){
    const r=await fetch('/api/tg_auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({initData:tg.initData})});
    const d=await r.json();
    if(d.ok){location.href='/panel?token='+d.token;}
  }
});</script>
</body></html>"""

def session_user(request):
    token = request.query.get("token") or ""
    s = SESSIONS.get(token)
    if not s or datetime.now() > s["expires_at"]:
        return None, None
    return token, s["user_id"]

async def index_page(request):
    return aio_web.Response(text=LOGIN_PAGE, content_type="text/html")

async def api_login(request):
    data = await request.json()
    code = (data.get("code") or "").strip()
    entry = LOGIN_CODES.get(code)
    if not entry or entry["used"] or datetime.now() > entry["expires_at"]:
        return aio_web.json_response({"ok": False, "message": "Код не найден, истёк или уже использован"}, status=403)
    entry["used"] = True
    token = secrets.token_hex(16)
    SESSIONS[token] = {"user_id": entry["user_id"], "expires_at": datetime.now() + timedelta(hours=SESSION_LIFETIME_HOURS)}
    return aio_web.json_response({"ok": True, "token": token})

# ================= АВТОВХОД ЧЕРЕЗ TELEGRAM MINI APP =================
def verify_init_data(init_data: str):
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.get("hash")
        if not received_hash:
            return None
        check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parse_qsl(init_data, keep_blank_values=True)) if k != "hash")
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        user = json.loads(pairs["user"])
        return int(user["id"])
    except Exception:
        return None

async def api_tg_auth(request):
    data = await request.json()
    user_id = verify_init_data(data.get("initData") or "")
    if not user_id:
        return aio_web.json_response({"ok": False}, status=403)
    create_user(user_id, str(user_id))
    token = secrets.token_hex(16)
    SESSIONS[token] = {"user_id": user_id, "expires_at": datetime.now() + timedelta(hours=SESSION_LIFETIME_HOURS)}
    return aio_web.json_response({"ok": True, "token": token})

PANEL_PAGE = """<!DOCTYPE html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Аниме-шахты</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',sans-serif}
body{background:#0d0d0f;color:#fff;min-height:100vh;padding-bottom:92px}
.header{padding:18px 16px 6px;font-size:30px;font-weight:800}
.stats{display:flex;justify-content:space-between;background:#1a1a1e;border-radius:14px;margin:8px 14px;padding:12px 16px;font-weight:700}
.card{background:#1a1a1e;border-radius:16px;margin:10px 14px;padding:16px}
.card h3{margin-bottom:10px}
.btn{width:100%;padding:14px;border:none;border-radius:12px;font-size:17px;font-weight:700;cursor:pointer;margin-top:10px}
.btn-green{background:#c6ff00;color:#111}
.btn-blue{background:#2d6cdf;color:#fff}
pre{white-space:pre-wrap;font-family:inherit;background:#0f1629;padding:12px;border-radius:8px;margin-top:10px}
table{width:100%;border-collapse:collapse}
th,td{padding:7px 4px;text-align:left;border-bottom:1px solid #2a2a2e;font-size:14px}
th{color:#999;font-weight:600}
.sum{margin-top:10px;font-weight:700;color:#c6ff00}
nav{position:fixed;bottom:0;left:0;right:0;background:#161618;display:flex;padding:8px 4px}
.tab{flex:1;text-align:center;color:#888;font-size:12px;cursor:pointer;padding:6px 0;border-radius:10px}
.tab .icon{font-size:20px;display:block}
.tab.active{color:#c6ff00}
.page{display:none}.page.visible{display:block}
</style></head><body>
<div class="header">Аниме-шахты</div>
<div class="stats">
  <span>💰 <span id="stat_balance">{balance}</span></span>
  <span>🏅 ур. <span id="stat_level">{level}</span></span>
</div>

<div class="page visible" id="page-home">
  <div class="card">
    <b>⛏️ Шахта</b>
    <pre id="out">Нажми кнопку — и в путь!</pre>
    <button class="btn btn-green" onclick="act('/api/mine')">⛏ Копать</button>
    <button class="btn btn-blue" onclick="act('/api/sell')">💰 Продать руду</button>
  </div>
</div>

<div class="page" id="page-inv"><div id="inv">{inventory}</div></div>
<div class="page" id="page-index">{index}</div>

<div class="page" id="page-profile">
  <div class="card"><b>👤 Профиль</b><pre id="profile_info">{profile}</pre></div>
</div>

<nav>
  <div class="tab active" onclick="showTab('page-home',this)"><span class="icon">🏠</span>Дом</div>
  <div class="tab" onclick="showTab('page-inv',this)"><span class="icon">🎒</span>Инвентарь</div>
  <div class="tab" onclick="showTab('page-index',this)"><span class="icon">📚</span>Индекс</div>
  <div class="tab" onclick="showTab('page-profile',this)"><span class="icon">👤</span>Профиль</div>
</nav>

<script>
const TOKEN=new URLSearchParams(location.search).get('token');
function showTab(id,el){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('visible'));
  document.getElementById(id).classList.add('visible');
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
}
async function act(url){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:TOKEN})});
  const d=await r.json();
  document.getElementById('out').innerText=d.message||'';
  if(d.ok){
    document.getElementById('profile_info').innerText=d.profile;
    document.getElementById('inv').innerHTML=d.inventory;
    document.getElementById('stat_balance').innerText=d.balance;
    document.getElementById('stat_level').innerText=d.level;
  }
}
</script></body></html>"""

async def panel_page(request):
    token, user_id = session_user(request)
    if not user_id:
        return aio_web.Response(text="Сессия истекла. Получи новый вход в боте: кнопка «Панель» или /panel", content_type="text/html", status=403)
    user = get_user(user_id)
    html = (PANEL_PAGE
        .replace("{balance}", str(user["balance"]))
        .replace("{level}", str(user["level"]))
        .replace("{inventory}", inventory_html(user))
        .replace("{index}", index_html())
        .replace("{profile}", profile_text(user_id)))
    return aio_web.Response(text=html, content_type="text/html")

async def api_action(request):
    data = await request.json()
    token = data.get("token") or ""
    s = SESSIONS.get(token)
    if not s or datetime.now() > s["expires_at"]:
        return aio_web.json_response({"ok": False, "message": "Сессия истекла. Получи новый вход: /panel"}, status=403)
    if request.path == "/api/mine":
        msg = perform_mine(s["user_id"])
    elif request.path == "/api/sell":
        msg = perform_sell(s["user_id"])
    else:
        return aio_web.json_response({"ok": False, "message": "Неизвестное действие"}, status=404)
    user = get_user(s["user_id"])
    return aio_web.json_response({
        "ok": True, "message": msg,
        "profile": profile_text(s["user_id"]),
        "inventory": inventory_html(user),
        "balance": user["balance"],
        "level": user["level"],
    })

def run_web():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = aio_web.Application()
    app.router.add_get("/", index_page)
    app.router.add_post("/api/login", api_login)
    app.router.add_post("/api/tg_auth", api_tg_auth)
    app.router.add_get("/panel", panel_page)
    app.router.add_post("/api/mine", api_action)
    app.router.add_post("/api/sell", api_action)
    port = int(os.getenv("PORT", 8080))
    runner = aio_web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = aio_web.TCPSite(runner, "0.0.0.0", port)
    loop.run_until_complete(site.start())
    loop.run_forever()


# ================= ЗАПУСК =================

async def main():
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.create_task(auto_mine_loop())   # фоновый автосбор каждые 3 часа
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
