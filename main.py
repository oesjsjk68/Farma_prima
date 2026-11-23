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
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
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
PANEL_URL = os.getenv("PANEL_URL") or os.getenv("APP_URL", "")

ADMIN_IDS = {5636309834}
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "minesuper")
BROADCAST_QUEUE = []

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Бот отвечает только в личке: в группах молчит ---
from aiogram import BaseMiddleware

class PrivateOnly(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None)
        if chat is not None and chat.type != "private":
            return
        return await handler(event, data)

dp.message.middleware(PrivateOnly())

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
    {"name": "10000 монет", "chance": 4,    "type": "money", "value": 10000},
    {"name": "50000 монет", "chance": 1.5,  "type": "money", "value": 50000},
    {"name": "200 опыта",   "chance": 10, "type": "xp",    "value": 200},
    {"name": "500 опыта",   "chance": 6,  "type": "xp",    "value": 500},
    {"name": "💥 ДЖЕКПОТ: скидка 50% на следующую покупку!", "chance": 3, "type": "jackpot", "value": 50},
]
JACKPOT_DISCOUNT = 50
JACKPOT_VALID_HOURS = 24

ORES = {
    "stone":   {"name": "🪨 Камень",        "price": 2,     "xp": 2},
    "iron":    {"name": "⚪ Железная руда", "price": 8,     "xp": 5},
    "copper":  {"name": "🟤 Медная руда",   "price": 20,    "xp": 10},
    "silver":  {"name": "⚪ Серебро",       "price": 50,    "xp": 15},
    "gold":    {"name": "🟡 Золотая руда",  "price": 60000, "xp": 25},
    "ruby":    {"name": "🔴 Рубин",         "price": 150,   "xp": 40},
    "diamond": {"name": "💎 Алмаз",         "price": 400,   "xp": 70},
    "mithril": {"name": "🔮 Мифрил",        "price": 1200,  "xp": 120},
}
ORE_KEYS = ["stone", "iron", "copper", "silver", "gold", "ruby", "diamond", "mithril"]

PICKAXES = [
    {"key": "wood",      "name": "🪵 Деревянная",    "power": 0,   "price": 0,         "level": 1},
    {"key": "stone",     "name": "⛏️ Каменная",      "power": 3,   "price": 5000,      "level": 10},
    {"key": "iron",      "name": "⛏️ Железная",      "power": 10,  "price": 250000,    "level": 20},
    {"key": "gold",      "name": "⛏️ Золотая",       "power": 25,  "price": 1000000,   "level": 35},
    {"key": "diamond",   "name": "⛏️ Алмазная",      "power": 50,  "price": 5000000,   "level": 50},
    {"key": "mithril",   "name": "⛏️ Мифриловая",    "power": 80,  "price": 25000000,  "level": 70},
    {"key": "ruby",      "name": "⛏️ Рубиновая",     "power": 110, "price": 100000000, "level": 90},
    {"key": "legendary", "name": "⛏️ ЛЕГЕНДАРНАЯ",   "power": 150, "price": 500000000, "level": 100},
]
PICKAXE_BY_KEY = {p["key"]: p for p in PICKAXES}

# ================= ПЕРСОНАЖИ =================
CHARACTERS = [
    {"key": "podrugi", "name": "👧 Подруги",          "bonus": 5,   "chance": 40,   "rar": "обычный"},
    {"key": "kazuya",  "name": "👦 Казуя",            "bonus": 15,  "chance": 30,   "rar": "обычный"},
    {"key": "minu",    "name": "🍇 Мину Минета",      "bonus": 10,  "chance": 25,   "rar": "обычный"},
    {"key": "usopp",   "name": "🎯 Усопп",            "bonus": 8,   "chance": 20,   "rar": "обычный"},
    {"key": "shinji",  "name": "🎧 Синдзи",           "bonus": 7,   "chance": 15,   "rar": "обычный"},
    {"key": "mumen",   "name": "🚴 Мумен Райдер",     "bonus": 20,  "chance": 10,   "rar": "редкий"},
    {"key": "tenten",  "name": "⚔️ Тен Тен",          "bonus": 25,  "chance": 8,    "rar": "редкий"},
    {"key": "buggy",   "name": "🤡 Багги",            "bonus": 28,  "chance": 6,    "rar": "редкий"},
    {"key": "yukiteru","name": "📱 Юкитэру Амано",    "bonus": 30,  "chance": 5,    "rar": "редкий"},
    {"key": "kazuma",  "name": "💧 Кадзума Сато",     "bonus": 35,  "chance": 4,    "rar": "редкий"},
    {"key": "luffy",   "name": "👒 Луффи",            "bonus": 55,  "chance": 2,    "rar": "эпический"},
    {"key": "jinwoo",  "name": "🗡️ Сон Джин Ву",     "bonus": 40,  "chance": 3,    "rar": "эпический"},
    {"key": "king",    "name": "👑 Кинг",             "bonus": 45,  "chance": 2.5,  "rar": "эпический"},
    {"key": "lelouch", "name": "♟️ Лелуш ви Британия","bonus": 75,  "chance": 1,    "rar": "легендарный"},
    {"key": "monoma",  "name": "📝 Нейто Монома",     "bonus": 60,  "chance": 1.5,  "rar": "легендарный"},
    {"key": "reigen",  "name": "🌀 Рейген",           "bonus": 65,  "chance": 1.2,  "rar": "легендарный"},
    {"key": "ichigo",  "name": "🗡️ Ичиго",           "bonus": 85,  "chance": 0.5,  "rar": "мифический"},
    {"key": "kurapika","name": "⛓️ Курапика",         "bonus": 80,  "chance": 0.8,  "rar": "мифический"},
    {"key": "killua",  "name": "⚡ Киллуа",           "bonus": 82,  "chance": 0.6,  "rar": "мифический"},
    {"key": "gojo",    "name": "🕶️ Годжо",           "bonus": 100, "chance": 0.3,  "rar": "мифический"},
    {"key": "adam",    "name": "👊 Адам",             "bonus": 90,  "chance": 0.4,  "rar": "мифический"},
    {"key": "simon",   "name": "⛏️ Симон",            "bonus": 110, "chance": 0.2,  "rar": "уникальный"},
    {"key": "alucard", "name": "🧛 Алукард",          "bonus": 130, "chance": 0.15, "rar": "уникальный"},
    {"key": "mob",     "name": "🌫️ Моб",              "bonus": 150, "chance": 0.1,  "rar": "уникальный"},
]
CHAR_BY_KEY = {c["key"]: c for c in CHARACTERS}
# Персонажи из старой коллекции: бонус сохраняется, имена показываются как есть
LEGACY_CHARS = {
    "novice":  {"name": "🧒 Новичок",               "bonus": 5,   "rar": "обычный"},
    "miner":   {"name": "👷 Опытный шахтёр",        "bonus": 10,  "rar": "обычный"},
    "digger":  {"name": "🧔 Старательный копатель", "bonus": 15,  "rar": "обычный"},
    "geomant": {"name": "🔮 Геомант",               "bonus": 20,  "rar": "редкий"},
    "golem":   {"name": "🗿 Каменный голем",        "bonus": 30,  "rar": "редкий"},
    "ice":     {"name": "❄️ Ледяная дева",          "bonus": 35,  "rar": "редкий"},
    "dragon":  {"name": "🐉 Огненный дракон",       "bonus": 40,  "rar": "эпический"},
    "phantom": {"name": "👻 Призрак шахты",         "bonus": 45,  "rar": "эпический"},
    "elf":     {"name": "🏹 Эльфийская разведчица", "bonus": 50,  "rar": "эпический"},
    "phoenix": {"name": "🔥 Феникс",                "bonus": 60,  "rar": "легендарный"},
    "titan":   {"name": "🌋 Титан бездны",          "bonus": 80,  "rar": "легендарный"},
    "king":    {"name": "👑 Король горы",           "bonus": 100, "rar": "мифический"},
}
def get_char(key):
    return CHAR_BY_KEY.get(key) or LEGACY_CHARS.get(key)

RARITY_COLORS = {
    "обычный": "#9aa3ad", "редкий": "#4aa3ff", "эпический": "#b46bff",
    "легендарный": "#ffc400", "мифический": "#ff5c5c", "уникальный": "#00e5c0",
}
CHAR_DROP_CHANCE = 0.03  # ~3% шанс встретить персонажа за копку


# ================= ЛОКАЦИИ ШАХТ =================
LOCATIONS = [
    {"key": "mine_1", "name": "🪨 Обычная шахта",      "level": 1,  "mult": 1.0, "desc": "базовая добыча"},
    {"key": "mine_2", "name": "🕳 Глубокая шахта",     "level": 15, "mult": 1.5, "desc": "все руды ×1,5"},
    {"key": "mine_3", "name": "🔥 Огненная пропасть",  "level": 30, "mult": 2.0, "desc": "все руды ×2,0"},
    {"key": "mine_4", "name": "❄️ Ледяные гроты",      "level": 45, "mult": 2.5, "desc": "все руды ×2,5"},
    {"key": "mine_5", "name": "✨ Зачарованные копи",  "level": 60, "mult": 3.0, "desc": "все руды ×3,0"},
    {"key": "mine_6", "name": "💎 Мифриловые глубины", "level": 80, "mult": 4.0, "desc": "все руды ×4,0"},
]
LOCATION_BY_KEY = {l["key"]: l for l in LOCATIONS}

# ================= КАРТИНКИ (папка images, раздаются по /img/) =================
IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
IMG_HOST = (os.getenv("IMG_HOST") or PANEL_URL).rstrip("/")
CHAR_IMG = {c["key"]: f"char_{c['key']}.jpg" for c in CHARACTERS}
# Все картинки, которые бот умеет подхватывать из папки images/:
#   char_<ключ>.jpg / .gif  — портреты персонажей (char_mob.gif и т.д.)
#   mine_1.jpg ... mine_6.jpg — локации шахт (показ при копке и в «Шахты»)
#   jackpot.jpg — крупный выигрыш в рулетке (x3 и джекпот) и джекпот в кейсе
#   banner.jpg — обложка магазина и «Шахт»
#   welcome.jpg — приветствие нового игрока (/start)
#   profile.jpg — профиль
#   bonus.jpg — бонус каждые 12 часов
#   top.jpg — таблица лидеров
#   pick_<ключ>.jpg — покупка кирки (pick_iron.jpg, pick_legendary.jpg ...)
#   transfer.jpg — перевод монет
#   promo.jpg — активация промокода
#   quests.jpg — забрал награду за задания
#   auto_mine.jpg — уведомление автосбора (раз в 3 часа)

def images_on(user_id):
    u = get_user(user_id)
    return bool(u) and u.get("images_on", 1) != 0

IMG_EXTENSIONS = (".gif", ".png", ".jpg", ".jpeg", ".webp")
def find_img_file(name):
    base = name
    if base.lower().endswith(IMG_EXTENSIONS):
        base = base[: base.rfind(".")]
    for ext in IMG_EXTENSIONS:
        p = os.path.join(IMG_DIR, base + ext)
        if os.path.exists(p):
            return base + ext
    return name

def img_url(name):
    real = find_img_file(name)
    return (IMG_HOST + "/img/" + real) if IMG_HOST else None

async def try_send_img(message, name, caption="", reply_markup=None):
    """Шлёт фото/GIF с подписью. Нет картинки/выключено — False, бот шлёт обычный текст."""
    if not images_on(message.from_user.id):
        return False
    url = img_url(name)
    if not url:
        return False
    send_caption = caption if (caption and len(caption) <= 1000) else ""
    try:
        if url.lower().endswith(".gif"):
            if send_caption:
                await message.answer_animation(animation=url, caption=send_caption, reply_markup=reply_markup)
            else:
                await message.answer_animation(animation=url, reply_markup=reply_markup)
                if caption:
                    await message.answer(caption, reply_markup=reply_markup)
            return True
        if send_caption:
            await message.answer_photo(photo=url, caption=send_caption, reply_markup=reply_markup)
        else:
            await message.answer_photo(photo=url, reply_markup=reply_markup)
            if caption:
                await message.answer(caption, reply_markup=reply_markup)
        return True
    except Exception:
        return False

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
DATA_DIR = os.getenv("DATA_DIR") or os.path.join(SCRIPT_DIR, "data")
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
        for col, typ in [("ore_silver", "INTEGER DEFAULT 0"), ("ore_ruby", "INTEGER DEFAULT 0"),
                         ("ore_diamond", "INTEGER DEFAULT 0"), ("ore_mithril", "INTEGER DEFAULT 0"),
                         ("q_date", "TEXT"), ("q_mine", "INTEGER DEFAULT 0"), ("q_sell", "INTEGER DEFAULT 0"),
                         ("q_spin", "INTEGER DEFAULT 0"), ("q_claimed", "INTEGER DEFAULT 0"),
                         ("images_on", "INTEGER DEFAULT 1")]:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
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
    "silver": "⚪ серебра", "ruby": "🔴 рубинов",
    "diamond": "💎 алмазов", "mithril": "🔮 мифрила",
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
    return sum((get_char(c) or {}).get("bonus", 0) for c in char_keys)

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
    loc = current_location(user)
    bonus_pct = min(100, char_bonus_percent(get_user_characters(user_id)))
    mult = loc["mult"] * (1 + bonus_pct / 100)
    luck = pick["power"] / 100 + lvl / 20
    base_chances = {"iron": 0.25, "copper": 0.15, "silver": 0.09,
                    "gold": 0.06, "ruby": 0.035, "diamond": 0.018, "mithril": 0.01}
    gained = {"stone": int(round((random.randint(3, 6) + lvl * 2 + pick["power"] // 10) * mult))}
    for key, base in base_chances.items():
        cnt = 1 if random.random() < min(0.95, base * (1 + luck)) else 0
        if key in ("iron", "copper") and cnt:
            cnt = random.randint(1, 2)
        gained[key] = int(round(cnt * mult)) if cnt else 0
    total_xp = sum(gained[k] * ORES[k]["xp"] for k in gained)
    upd = {f"ore_{k}": user.get(f"ore_{k}", 0) + v for k, v in gained.items()}
    upd["auto_last_at"] = datetime.now().isoformat()
    update_user(user_id, **upd)
    add_xp_and_level_up(user_id, user, total_xp)
    text = f"🤖 Автосбор (ур. {lvl}, {loc['name']}) — шахта собрала ресурсы, пока тебя не было:\n"
    for k in ORE_KEYS:
        if gained.get(k):
            text += f"{ORES[k]['name']} × {gained[k]}\n"
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
                    sent = False
                    if images_on(uid):
                        url = img_url("auto_mine.jpg")
                        if url:
                            try:
                                await bot.send_photo(uid, photo=url, caption=text[:1000])
                                sent = True
                            except Exception:
                                sent = False
                    if not sent:
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
    kb = []
    if PANEL_URL:
        kb.append([KeyboardButton(text="📱 Открыть игру", web_app=WebAppInfo(url=PANEL_URL))])
    kb.append([
        [KeyboardButton(text="⛏️ Накопать"), KeyboardButton(text="💰 Продать руду")],
        [KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="📦 Кейс")],
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="🎲 Рулетка")],
        [KeyboardButton(text="🗺 Шахты"), KeyboardButton(text="🧙 Персонажи")],
        [KeyboardButton(text="🤖 Автосбор"), KeyboardButton(text="🎯 Задания")],
        [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="💼 Профиль")],
        [KeyboardButton(text="🖼 Картинки"), KeyboardButton(text="🖥 Панель")],
        [KeyboardButton(text="⚙️ Админ")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True,
                               input_field_placeholder="Выбери действие ⬇️")

def shop_keyboard():
    kb = [[KeyboardButton(text=f"⚒️ Купить {p['name']}")] for p in PICKAXES if p["price"] > 0]
    kb.append([KeyboardButton(text="📜 История покупок"), KeyboardButton(text="ℹ️ Моя скидка")])
    kb.append([KeyboardButton(text="↩️ Вернуть покупку"), KeyboardButton(text="🔙 Назад")])
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
    bonus_pct = min(100, char_bonus_percent(get_user_characters(user_id)))
    mult = loc["mult"] * (1 + bonus_pct / 100)
    gained = {"stone": int(round((random.randint(2, 4) + pick["power"] // 10 + user["level"] - 1) * mult))}
    base_chances = {"iron": 0.20, "copper": 0.10, "silver": 0.07,
                    "gold": 0.05, "ruby": 0.03, "diamond": 0.015, "mithril": 0.008}
    luck = pick["power"] / 100 + (user["level"] - 1) / 50
    for key, base in base_chances.items():
        cnt = 1 if random.random() < min(0.95, base * (1 + luck)) else 0
        if key in ("iron", "copper") and cnt:
            cnt = random.randint(1, 2)
        gained[key] = int(round(cnt * mult)) if cnt else 0
    total_xp = sum(gained[k] * ORES[k]["xp"] for k in gained)
    upd = {f"ore_{k}": user.get(f"ore_{k}", 0) + v for k, v in gained.items()}
    upd["last_mine_at"] = datetime.now().isoformat()
    update_user(user_id, **upd)
    new_level, levelups = add_xp_and_level_up(user_id, user, total_xp)
    text = f"⛏️ Локация: {loc['name']}"
    if mult != 1.0:
        text += f" (добыча ×{mult:g})"
    text += "\n\nТы накопал (ушло в рюкзак):\n"
    for k in ORE_KEYS:
        if gained.get(k):
            text += f"{ORES[k]['name']} × {gained[k]}\n"
    text += f"\n📈 Получено опыта: {total_xp}\n💡 Продай руду через «💰 Продать руду»"
    if levelups > 0:
        text += f"\n🎉 Новый уровень: {new_level}! Теперь руды будет больше."
    text += try_char_drop(user_id)
    bump_quest(user_id, "mine")
    return text


# --- Ядро: продать ---
def perform_sell(user_id):
    user = get_user(user_id)
    if not user:
        return "Сначала запусти бота через /start"
    prices = get_prices()
    lines, total = [], 0
    zero = {}
    for key in ORE_KEYS:
        count = int(user.get(f"ore_{key}", 0) or 0)
        zero[f"ore_{key}"] = 0
        if count > 0:
            money = count * prices.get(key, ORES[key]["price"])
            lines.append(f"{ORES[key]['name']} × {count} = {money} монет")
            total += money
    if total == 0:
        return "Рюкзак пуст! Сначала накопай руду через «⛏️ Накопать»."
    zero["balance"] = user["balance"] + total
    update_user(user_id, **zero)
    bump_quest(user_id, "sell")
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
        '<div class="card"><h3>🧙 Персонажи</h3><table><tr><th>Персонаж</th><th>Бонус</th><th>Шанс</th></tr>'
        + "".join(f"<tr><td>{c['name']}</td><td>+{c['bonus']}%</td><td>{c['chance']}%</td></tr>" for c in CHARACTERS)
        + "</table></div>"
    )

# ================= ХЕНДЛЕРЫ ИГРОКА =================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    user = get_user(user_id)
    if not user:
        create_user(user_id, username)
        welcome = (
            f"Привет, {username}! Ты стал шахтёром.\n"
            "Копай руду, продавай её, качай уровни и покупай кирки получше!\n"
            "🎁 Бонус — раз в 12 часов.\n"
            "📦 Ежедневный кейс — раз в 24 часа, шанс поймать ДЖЕКПОТ: скидка 50%!\n"
            "🎲 Рулетка откроется с 20 уровня.\n"
            "💰 За каждую покупку кирки — скидка 1% (до 15%).\n"
            "🖥 Кнопка «Панель» — вход в веб-панель без кода."
        )
        if not await try_send_img(message, "welcome.jpg", welcome):
            await message.answer(welcome)
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
        text = f"🎉 Промокод активирован! +{amount} {PROMO_TYPES[ptype]}"
        if not await try_send_img(message, "promo.jpg", text, reply_markup=main_keyboard()):
            await message.answer(text, reply_markup=main_keyboard())

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
        text = (
            f"💸 Перевод выполнен!\n"
            f"{transferred} монет ушли игроку {target_id}.\n"
            f"💰 Твой баланс: {me['balance']} монет"
        )
        if not await try_send_img(message, "transfer.jpg", text, reply_markup=main_keyboard()):
            await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "⛏️ Накопать")
async def mine_action(message: Message):
    user = ensure_user(message)
    text = perform_mine(user["user_id"])
    if images_on(user["user_id"]) and text and not text.startswith("Подожди"):
        loc = current_location(user)
        if await try_send_img(message, f"{loc['key']}.jpg", text):
            return
    await message.answer(text)


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
    top_text = "\n".join(lines)
    if not await try_send_img(message, "top.jpg", top_text, reply_markup=main_keyboard()):
        await message.answer(top_text, reply_markup=main_keyboard())

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
    text = (
        f"🎁 Ты получил бонус: {bonus} монет!\n"
        f"Следующий — через {get_setting('bonus_hours', BONUS_COOLDOWN_HOURS)} часов."
    )
    if not await try_send_img(message, "bonus.jpg", text, reply_markup=main_keyboard()):
        await message.answer(text, reply_markup=main_keyboard())

# ================= ЕЖЕДНЕВНЫЙ КЕЙС =================

@dp.message(F.text == "📦 Кейс")
async def open_case(message: Message):
    user_id = message.from_user.id
    ensure_user(message)
    # маленькая анимация открытия кейса
    opening_msg = await message.answer("📦 Кейс трясётся...")
    for step in range(4):
        try:
            await opening_msg.edit_text("📦 Открываем кейс... " + "💥" * (step + 1))
        except Exception:
            pass
        await asyncio.sleep(0.6)
    reward, result = perform_case(user_id)
    if reward is None:
        try:
            await opening_msg.delete()
        except Exception:
            pass
        await message.answer(result, reply_markup=main_keyboard())
        return
    big = reward["type"] == "jackpot" or (reward["type"] == "money" and reward["value"] >= 50000)
    if images_on(user_id) and big:
        ok = await try_send_img(message, "jackpot.jpg", result, reply_markup=main_keyboard())
        if ok:
            try:
                await opening_msg.delete()
            except Exception:
                pass
            return
    await message.answer(result, reply_markup=main_keyboard())
    try:
        await opening_msg.delete()
    except Exception:
        pass


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
        f"🎰 Р У Л Е Т К А\n\n"
        f"Сектора колеса:\n"
        f"• 💥 Джекпот x5 — 2%\n"
        f"• 🔥 Выигрыш x3 — 8%\n"
        f"• ✅ Выигрыш x2 — 20%\n"
        f"• ➖ Возврат ставки — 15%\n"
        f"• ❌ Проигрыш — 55%\n\n"
        f"💸 Ставка: от {ROULETTE_MIN_BET} до {ROULETTE_MAX_BET} монет.\n"
        f"💰 Твой баланс: {user['balance']} монет.\n\n"
        f"Напиши сумму ставки числом, например: 100\n"
        f"Или отправь «отмена», чтобы передумать."
    )

@dp.message(F.text == "отмена")
async def roulette_cancel(message: Message):
    if pending_roulette.pop(message.from_user.id, None):
        await message.answer("Ставка отменена. Возвращаемся к шахтам!")
    else:
        raise SkipHandler  # не наш случай — пусть обрабатывают другие хендлеры

SECTOR_ICONS = ["💥", "🔥", "✅", "➖", "❌"]

def wheel_text(active_idx):
    icons = SECTOR_ICONS
    lines = ["🎰 Р У Л Е Т К А", ""]
    for i, s in enumerate(ROULETTE_SECTORS):
        if i == active_idx:
            lines.append(f"▶️ {icons[i]} {s['name']} ◀️")
        else:
            lines.append(f"▫️ {icons[i]} {s['name']}")
    lines.append("")
    lines.append("⏳ Момент истины...")
    return "\n".join(lines)


async def spin_animation(msg, final_idx):
    clock = ["🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚", "🕛"]
    frames = len(ROULETTE_SECTORS)
    seq = []
    pos = random.randrange(frames)
    for _ in range(2 * frames + random.randint(0, frames - 1)):
        seq.append(pos % frames)
        pos += 1
    for back in range(3, 0, -1):
        seq.append((final_idx - back) % frames)
    seq.append(final_idx)
    seq.append(final_idx)
    for n, idx in enumerate(seq):
        head = clock[n % len(clock)]
        try:
            await msg.edit_text(f"{head} " + wheel_text(idx))
        except Exception:
            pass
        t = n / max(1, len(seq) - 1)
        await asyncio.sleep(0.35 + t * t * 0.6)


@dp.message(F.text.regexp(r"^\d+$"))
async def roulette_bet(message: Message):
    user_id = message.from_user.id
    if not pending_roulette.pop(user_id, None):
        raise SkipHandler  # это не ставка — пусть идёт дальше (в т.ч. в админ-диалог)

    user = get_user(user_id)
    if not user:
        await message.answer("Сначала запусти бота через /start")
        return

    try:
        bet = int(message.text)
    except ValueError:
        pending_roulette[user_id] = True
        await message.answer("Отправь сумму ставки числом, например: 100")
        return
    if bet < ROULETTE_MIN_BET or bet > ROULETTE_MAX_BET:
        pending_roulette[user_id] = True
        await message.answer(f"Ставка должна быть от {ROULETTE_MIN_BET} до {ROULETTE_MAX_BET} монет. Отправь сумму заново.")
        return

    sector, result, delta = perform_spin(user_id, bet)
    if sector is None:
        pending_roulette[user_id] = True
        await message.answer(result)
        return

    final_idx = ROULETTE_SECTORS.index(sector)
    spin_msg = await message.answer(wheel_text(0))
    await spin_animation(spin_msg, final_idx)
    try:
        await spin_msg.delete()
    except Exception:
        pass

    if images_on(user_id) and sector["mult"] >= 3:
        ok = await try_send_img(message, "jackpot.jpg", result)
        if ok:
            return
    await message.answer(result, reply_markup=main_keyboard())


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
    buy_text = (
        f"✅ Покупка завершена!\n\n"
        f"⛏️ Кирка: {wanted['name']}\n"
        f"💰 Оплачено: {final_price} монет (скидка {discount}%)\n"
        f"📈 Новый баланс: {new_balance} монет\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        f"🏷 Твоя скидка теперь: {new_discount}%"
        + ("\n💥 Джекпот-скидка использована и сгорела." if had_jackpot else "") + "\n"
        f"↩️ Вернуть покупку можно командой /возврат в течение {REFUND_WINDOW_MIN} минут."
    )
    if not await try_send_img(message, f"pick_{wanted['key']}.jpg", buy_text, reply_markup=main_keyboard()):
        await message.answer(buy_text, reply_markup=main_keyboard())

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
    if await try_send_img(message, "profile.jpg", profile_text(message.from_user.id), reply_markup=main_keyboard()):
        return
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
    kb = ReplyKeyboardMarkup(keyboard=kb_rows, resize_keyboard=True)
    sent = await try_send_img(message, "banner.jpg", "\n".join(lines))
    if sent:
        await message.answer("👆 Выбери локацию кнопкой ниже:", reply_markup=kb)
    else:
        await message.answer("\n".join(lines), reply_markup=kb)


# ================= ПЕРСОНАЖИ (хендлер) =================
@dp.message(Command("персонажи"))
@dp.message(F.text == "🧙 Персонажи")
async def characters_handler(message: Message):
    user = ensure_user(message)
    uid = user["user_id"]
    owned = get_user_characters(uid)
    if not owned:
        await message.answer("🧙 У тебя пока нет персонажей.\nКопай руду — с шансом ~3% за копку можно встретить персонажа, он даст постоянный бонус к добыче!", reply_markup=main_keyboard())
        return
    lines = ["🧙 Твои персонажи:"]
    first_img = None
    for key in owned:
        c = get_char(key)
        if c is None:
            lines.append("• Персонаж из старой коллекции — бонус сохранён")
            continue
        lines.append(f"• {c['name']} ({c['rar']}) — +{c['bonus']}% к добыче")
        if first_img is None:
            first_img = CHAR_IMG.get(key)
    lines.append(f"\n💪 Суммарный бонус: +{min(100, char_bonus_percent(owned))}% к добыче руды")
    if images_on(uid) and first_img:
        ok = await try_send_img(message, first_img, "\n".join(lines))
        if ok:
            return
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
            [InlineKeyboardButton(text="🌐 Открыть панель", url=url)],
            [InlineKeyboardButton(text="📱 Открыть игру (Mini App)", web_app=WebAppInfo(url=PANEL_URL))],
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


# ================= ЕЖЕДНЕВНЫЕ ЗАДАНИЯ + ОБЩИЕ ЯДРА (бот и панель) =================

QUEST_GOALS = {"mine": 20, "sell": 3, "spin": 5}
QUEST_REWARD = 6500
QUEST_TITLES = {
    "mine": "⛏️ Накопать руды 20 раз",
    "sell": "💰 Продать руду 3 раза",
    "spin": "🎲 Крутить рулетку 5 раз",
}

def quest_refresh(user):
    today = datetime.now().strftime("%Y-%m-%d")
    if user.get("q_date") != today:
        update_user(user["user_id"], q_date=today, q_mine=0, q_sell=0, q_spin=0, q_claimed=0)
        user = get_user(user["user_id"])
    return user

def bump_quest(user_id, key):
    col = {"mine": "q_mine", "sell": "q_sell", "spin": "q_spin"}.get(key)
    if not col:
        return
    user = get_user(user_id)
    if not user or user.get("q_date") != datetime.now().strftime("%Y-%m-%d"):
        return
    with db_lock:
        conn = get_conn()
        conn.execute(f"UPDATE users SET {col} = {col} + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

def quests_text(user_id):
    user = get_user(user_id)
    if not user:
        return "Сначала запусти бота через /start"
    user = quest_refresh(user)
    all_done = True
    lines = ["🎯 Ежедневные задания (обновляются каждый день):\n"]
    for k, goal in QUEST_GOALS.items():
        cnt = min(int(user.get(f"q_{k}") or 0), goal)
        lines.append(f"{QUEST_TITLES[k]} — {cnt}/{goal} {'✅' if cnt >= goal else '⬜'}")
        if cnt < goal:
            all_done = False
    lines.append(f"\n🎁 Награда за все задания: {QUEST_REWARD} монет")
    if all_done and not user.get("q_claimed"):
        lines.append("Жми «🎁 Забрать награду»!")
    elif all_done:
        lines.append("Награда за сегодня получена ✅ Новые задания — завтра!")
    return "\n".join(lines)

def claim_quests(user_id):
    user = quest_refresh(get_user(user_id))
    if not user:
        return None, "Сначала запусти бота через /start"
    if not all(min(int(user.get(f"q_{k}") or 0), g) >= g for k, g in QUEST_GOALS.items()):
        return None, "Задания ещё не все выполнены — копай, продавай и крути рулетку!"
    if user.get("q_claimed"):
        return None, "Награда за сегодня уже получена ✅"
    update_user(user_id, balance=user["balance"] + QUEST_REWARD, q_claimed=1)
    return QUEST_REWARD, f"🎉 Все задания выполнены! Награда: +{QUEST_REWARD} монет!"

# --- Ядро кейса (бот + панель) ---
def perform_case(user_id):
    user = get_user(user_id)
    if not user:
        return None, "Сначала запусти бота через /start"
    if not can_case(user):
        hours, minutes = hours_until_case(user)
        return None, f"📦 Кейс уже открыт! Следующий — через {hours} ч. {minutes} мин."
    update_user(user_id, last_case_at=datetime.now().isoformat())
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
            f"💥 Твой следующий дроп в магазине будет со скидкой {JACKPOT_DISCOUNT}!\n"
            f"Действует до: {until.strftime('%d.%m.%Y %H:%M')}\n"
            f"Успей купить кирку в «🛒 Магазине»!"
        )
    result += f"\n\n⏰ Следующий кейс — через {get_setting('case_hours', CASE_COOLDOWN_HOURS)} ч."
    return reward, result

# --- Ядро рулетки (бот + панель) ---
def perform_spin(user_id, bet):
    user = get_user(user_id)
    if not user:
        return None, "Сначала запусти бота через /start", None
    if user["level"] < ROULETTE_MIN_LEVEL:
        return None, f"🔒 Рулетка откроется с {ROULETTE_MIN_LEVEL} уровня. Твой уровень: {user['level']}.", None
    if not (ROULETTE_MIN_BET <= bet <= ROULETTE_MAX_BET):
        return None, f"Ставка должна быть от {ROULETTE_MIN_BET} до {ROULETTE_MAX_BET} монет.", None
    if user["balance"] < bet:
        return None, f"Не хватает монет! У тебя {user['balance']}, а нужно {bet}.", None
    now_ts = datetime.now().timestamp()
    last_spin = roulette_cooldowns.get(user_id)
    if last_spin and now_ts - last_spin < ROULETTE_COOLDOWN_SEC:
        return None, f"🎲 Крути не чаще раза в {ROULETTE_COOLDOWN_SEC} сек. Подожди ещё {int(ROULETTE_COOLDOWN_SEC - (now_ts - last_spin))} сек.", None
    roll = random.random()
    cumulative = 0.0
    sector = ROULETTE_SECTORS[-1]
    for s in ROULETTE_SECTORS:
        cumulative += s["chance"]
        if roll < cumulative:
            sector = s
            break
    roulette_cooldowns[user_id] = now_ts
    win = int(bet * sector["mult"])
    delta = win - bet
    new_balance = user["balance"] + delta
    update_user(user_id, balance=new_balance)
    bump_quest(user_id, "spin")
    result = f"🎯 Колесо остановилось!\n\n{sector['name']}"
    if delta > 0:
        result += f"\n\n🎉 Ставка {bet} → выигрыш {win} монет!\n📈 Прибыль: +{delta}"
    elif delta == 0:
        result += f"\n\n⚪ Ставка {bet} вернулась на место."
    else:
        result += f"\n\n💀 Ставка {bet} сгорела."
    result += f"\n\n💰 Баланс: {new_balance} монет"
    return sector, result, delta

# --- Ядро бонуса (для панели) ---
def perform_bonus_core(user_id):
    user = get_user(user_id)
    if not user:
        return None, "Сначала запусти бота через /start"
    if not can_bonus(user):
        hours, minutes = hours_until_bonus(user)
        return None, f"Бонус через {hours} ч {minutes} мин"
    amount = get_setting("bonus_amount", BONUS_AMOUNT)
    update_user(user_id, balance=user["balance"] + amount, last_bonus_at=datetime.now().isoformat())
    return amount, f"🎁 Бонус +{amount} монет! Возвращайся через {get_setting('bonus_hours', BONUS_COOLDOWN_HOURS)} ч."

@dp.message(F.text == "🎯 Задания")
async def quests_cmd(message: Message):
    ensure_user(message)
    uid = message.from_user.id
    text = quests_text(uid)
    user = quest_refresh(get_user(uid))
    all_done = all(min(int(user.get(f"q_{k}") or 0), g) >= g for k, g in QUEST_GOALS.items())
    if all_done and not user.get("q_claimed"):
        await message.answer(text, reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🎁 Забрать награду")], [KeyboardButton(text="🔙 Назад")]],
            resize_keyboard=True))
    else:
        await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "🎁 Забрать награду")
async def quests_claim(message: Message):
    ensure_user(message)
    uid = message.from_user.id
    ok, msg = claim_quests(uid)
    if ok:
        msg += f"\n💰 Баланс: {get_user(uid)['balance']} монет"
    if not await try_send_img(message, "quests.jpg", msg, reply_markup=main_keyboard()):
        await message.answer(msg, reply_markup=main_keyboard())

@dp.message(F.text == "🖼 Картинки")
async def toggle_images(message: Message):
    ensure_user(message)
    uid = message.from_user.id
    user = get_user(uid)
    new = 0 if user.get("images_on", 1) else 1
    update_user(uid, images_on=new)
    state = "ВКЛ — копка и события будут с фото" if new else "ВЫКЛ — только текст"
    await message.answer(f"🖼 Картинки в боте: {state}", reply_markup=main_keyboard())

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
        "задания": quests_cmd,
        "картинки": toggle_images,
    }
    handler = commands.get(text)
    if handler:
        await handler(message)
    else:
        await message.answer(
            "Не понял 🤔 Нажми кнопку на клавиатуре или напиши:\n"
            "копать, продать, профиль, бонус, кейс, топ, магазин, рулетка, панель"
        )

# ================= ВЕБ-ПАНЕЛЬ (AIOHTTP, встроенная — 8 вкладок, картинки) =================

LOGIN_PAGE = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Аниме-шахты — вход</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>body{font-family:sans-serif;background:#0d0d0f;color:#eee;display:flex;flex-direction:column;align-items:center;padding-top:60px;margin:0}
.card{background:#1a1a1e;padding:30px;border-radius:16px;text-align:center;max-width:340px;width:92%}
input{padding:10px;font-size:18px;border-radius:8px;border:none;text-align:center;width:160px;background:#24242a;color:#fff}
button{padding:11px 26px;font-size:16px;background:#c6ff00;color:#111;border:none;border-radius:10px;cursor:pointer;margin-top:12px;font-weight:700}
.err{color:#ff6b6b;margin-top:10px;min-height:20px}
h1{font-size:22px;margin-bottom:6px}</style></head>
<body><div class="card"><h1>⛏️ Аниме-шахты</h1>
<img src="/img/banner.jpg" style="width:100%;border-radius:12px;margin:8px 0" onerror="this.style.display='none'">
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

PANEL_PAGE = r"""<!DOCTYPE html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Аниме-шахты</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{margin:0;box-sizing:border-box;font-family:'Segoe UI',sans-serif;-webkit-tap-highlight-color:transparent}
body{background:#0d0d0f;color:#fff;min-height:100vh;padding-bottom:96px}
.header{padding:14px 16px;font-size:24px;font-weight:800;display:flex;justify-content:space-between;align-items:center;gap:6px}
.chip{background:#1a1a1e;border-radius:12px;padding:8px 10px;font-weight:700;font-size:14px}
.chip.bal{animation:pulse 2.4s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(198,255,0,.35)}50%{box-shadow:0 0 0 7px rgba(198,255,0,0)}}
.card{background:#1a1a1e;border-radius:16px;margin:10px 14px;padding:14px;animation:appear .35s ease both}
@keyframes appear{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.card h3{margin-bottom:8px;font-size:16px}
.btn{width:100%;padding:12px;border:none;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer;margin-top:8px;transition:transform .08s}
.btn:active{transform:scale(.95)}
.g{background:#c6ff00;color:#111}.b{background:#2d6cdf;color:#fff}.r{background:#c0392b;color:#fff}.gr{background:#333;color:#999}
input{width:100%;padding:10px;border-radius:8px;border:none;background:#24242a;color:#fff;font-size:15px;margin-top:6px}
pre{white-space:pre-wrap;font-family:inherit;color:#cfd8dc;font-size:14px}
table{width:100%;border-collapse:collapse}th,td{padding:6px 4px;text-align:left;border-bottom:1px solid #2a2a2e;font-size:13px}th{color:#999}
.sum{margin-top:8px;font-weight:700;color:#c6ff00}
.mine-img{width:100%;border-radius:12px;margin-bottom:10px}
.item{display:flex;gap:10px;align-items:center;margin-top:10px;cursor:pointer;background:#232329;border-radius:12px;padding:9px;transition:transform .1s,background .2s}
.item:active{transform:scale(.97);background:#2b2b34}
.item img,.item .ph{width:56px;height:56px;border-radius:10px;object-fit:cover;display:flex;align-items:center;justify-content:center;font-size:26px;background:#2e2e38;flex:none}
.item .nm{flex:1;min-width:0}.item .nm small{color:#8b8b95;display:block;font-size:12px}
.ok{color:#c6ff00}.no{color:#ff6b6b}.tag{color:#8b8b95;font-size:12px}
#toast{position:fixed;top:12px;left:50%;transform:translateX(-50%);background:#24242a;color:#fff;padding:10px 16px;border-radius:10px;display:none;z-index:9;max-width:90%;text-align:center;font-size:14px;animation:toastin .25s ease}
@keyframes toastin{from{opacity:0;transform:translateX(-50%) translateY(-8px)}to{opacity:1;transform:translateX(-50%)}}
nav{position:fixed;bottom:0;left:0;right:0;background:#161618;display:flex;padding:6px 2px;z-index:10}
.tab{flex:1;text-align:center;color:#888;font-size:10px;cursor:pointer;padding:6px 0;transition:color .2s}
.tab .i{font-size:18px;display:block}.tab.active{color:#c6ff00}
.page{display:none}.page.visible{display:block}
.fly{position:fixed;font-weight:800;color:#c6ff00;font-size:18px;pointer-events:none;z-index:60;animation:flyup 1s ease forwards}
@keyframes flyup{from{opacity:1;transform:translateY(0)}to{opacity:0;transform:translateY(-60px)}}
#modal{position:fixed;inset:0;background:rgba(0,0,0,.72);display:none;z-index:50;align-items:flex-end;justify-content:center}
#modal.open{display:flex}
.mbox{background:#1a1a1e;border-radius:18px 18px 0 0;width:100%;max-width:480px;padding:16px;animation:slideup .25s ease;max-height:85vh;overflow:auto}
@keyframes slideup{from{transform:translateY(50px);opacity:.4}to{transform:none;opacity:1}}
.mbig{width:78%;max-height:230px;object-fit:contain;border-radius:12px;margin:10px auto;display:block}
#jp{position:fixed;inset:0;display:none;align-items:center;justify-content:center;z-index:70;background:radial-gradient(circle,rgba(255,196,0,.25),rgba(0,0,0,.9));font-size:34px;font-weight:900;color:#ffc400;text-shadow:0 0 24px #ff8c00;animation:jpzoom .5s ease}
#jp.show{display:flex}
@keyframes jpzoom{from{transform:scale(.3);opacity:0}to{transform:scale(1);opacity:1}}
.spin{animation:shakex .5s}
@keyframes shakex{0%,100%{transform:none}25%{transform:translateX(-4px)}75%{transform:translateX(4px)}}
</style></head><body>
<div class="header">⛏️ Аниме-шахты
<div><span class="chip bal" id="balchip">💰 <span id="bal">0</span></span> <span class="chip">🏅 <span id="lvl">1</span></span></div></div>
<div id="toast"></div>
<div id="content"></div>
<div id="modal" onclick="if(event.target===this)this.classList.remove('open')"><div id="mbox" class="mbox"></div></div>
<div id="jp">💥 ДЖЕКПОТ!</div>
<nav id="nav"></nav>
<script>
let S=null,TOKEN=new URLSearchParams(location.search).get('token')||localStorage.getItem('shaxty_t')||'',cur='home',reauth=false;
const tg=window.Telegram&&window.Telegram.WebApp;
function saveT(t){TOKEN=t;try{localStorage.setItem('shaxty_t',t)}catch(e){}}
async function initAuth(){
 if(!tg||!tg.initData)return false;
 try{const r=await fetch('/api/tg_auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({initData:tg.initData})});const d=await r.json();if(d.ok){saveT(d.token);return true}}catch(e){}
 return false;
}
function noAuthScreen(){document.getElementById('content').innerHTML='<div class="card" style="text-align:center"><h3>🔐 Нужен вход из Telegram</h3><p class="tag" style="margin-top:8px">Открой игру кнопкой «📱 Открыть игру» прямо в боте — панель подключится автоматически, без кодов. Либо нажми в боте «🖥 Панель» и получи личную ссылку.</p></div>'}
async function api(ep,body){
 let r=await fetch('/api/'+ep,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{token:TOKEN})});
 if(r.status===403&&!reauth){reauth=true;if(await initAuth()){r=await fetch('/api/'+ep,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{token:TOKEN})})}}
 if(r.status===403){noAuthScreen();throw new Error('auth')}
 return await r.json();
}
async function refresh(){const d=await api('state');if(!d.ok){document.getElementById('content').innerHTML='<div class="card">'+(d.error||'Ошибка')+'</div>';return}S=d;draw()}
function esc(s){return (s+'').replace(/</g,'&lt;').replace(/\n/g,'<br>')}
function rarc(r){return {'обычный':'#9aa3ad','редкий':'#4aa3ff','эпический':'#b46bff','легендарный':'#ffc400','мифический':'#ff5c5c','уникальный':'#00e5c0'}[r]||'#fff'}
let AC=null;
function tone(f,d,t,v,dl){try{if(!AC)AC=new(window.AudioContext||window.webkitAudioContext)();const o=AC.createOscillator(),g=AC.createGain(),now=AC.currentTime+(dl||0);o.type=t||'sine';o.frequency.value=f;g.gain.setValueAtTime(v||.12,now);g.gain.exponentialRampToValueAtTime(.0001,now+d);o.connect(g);g.connect(AC.destination);o.start(now);o.stop(now+d)}catch(e){}}
const SND={click:()=>tone(520,.07,'sine',.06),coin:()=>{tone(900,.09,'square',.07);tone(1350,.12,'square',.07,.07)},win:()=>{tone(523,.16,'sine',.1);tone(659,.16,'sine',.1,.1);tone(784,.24,'sine',.12,.2)},lose:()=>tone(150,.35,'sawtooth',.12),jackpot:()=>{[523,659,784,1046,1318,1568].forEach((f,i)=>tone(f,.3,'triangle',.14,i*.1))}};
function draw(){
 if(!S)return;
 document.getElementById('bal').textContent=S.balance;
 document.getElementById('lvl').textContent=S.level;
 document.getElementById('nav').innerHTML=TABS.map(t=>'<div class="tab '+(t[0]===cur?'active':'')+'" data-tab="'+t[0]+'"><span class="i">'+t[1]+'</span>'+t[2]+'</div>').join('');
 document.getElementById('content').innerHTML='<div class="page visible">'+(PAGES[cur]||function(){return ''})()+'</div>';
}
function go(t){cur=t;draw()}
function toast(m){const el=document.getElementById('toast');el.textContent=m;el.style.display='block';setTimeout(()=>el.style.display='none',4000)}
function fly(){const el=document.createElement('span');el.className='fly';el.textContent='+💰';const c=document.getElementById('balchip').getBoundingClientRect();el.style.left=(c.left+10)+'px';el.style.top=(c.bottom+6)+'px';document.body.appendChild(el);setTimeout(()=>el.remove(),1000)}
function jpShow(){const el=document.getElementById('jp');el.classList.add('show');setTimeout(()=>el.classList.remove('show'),1800)}
function closeModal(){document.getElementById('modal').classList.remove('open')}
function openModal(kind,idx){
 let it=null;
 if(kind==='pick')it=S.shop[idx];
 if(kind==='loc')it=S.locations[idx];
 if(kind==='char')it=S.characters[idx];
 if(!it)return;
 SND.click();
 let h='<div class="mbox"><h3>'+esc(it.name)+'</h3>';
 if(it.img)h+='<img class="mbig" src="'+it.img+'" onerror="this.remove()">';
 if(kind==='pick'){
  h+='<p>Сила: <b>'+it.power+'</b> • Требуется уровень: <b>'+it.level+'</b></p><p class="sum">Цена: '+it.price+' монет</p>';
  if(it.owned)h+='<p class="ok">✅ Уже в руках</p>';
  else if(it.next&&S.level>=it.level)h+='<button class="btn g" data-buy="'+it.key+'">Купить за '+it.price+'</button>';
  else if(it.next)h+='<p class="no">🔒 Нужен уровень '+it.level+'</p>';
  else h+='<p class="tag">Сначала купи предыдущую кирку</p>';
 }
 if(kind==='loc'){
  h+='<p>Множитель добычи: <b>×'+it.mult+'</b></p><p class="tag">'+esc(it.desc)+'</p>';
  if(it.current)h+='<p class="ok">📍 Ты сейчас здесь</p>';
  else if(it.available)h+='<button class="btn g" data-loc="'+it.key+'">Перейти сюда</button>';
  else h+='<p class="no">🔒 Откроется с '+it.level+' уровня</p>';
 }
 if(kind==='char'){
  h+='<p>Редкость: <b style="color:'+rarc(it.rar)+'">'+esc(it.rar)+'</b></p><p>Бонус: <b>+'+it.bonus+'%</b> к добыче</p><p>Шанс встретить при копке: <b>'+it.chance+'%</b></p>';
  h+=it.owned?'<p class="ok">✅ Уже в коллекции</p>':'<p class="tag">Ещё не встретился — копай дальше!</p>';
 }
 h+='<button class="btn gr" data-close="1">Закрыть</button></div>';
 document.getElementById('mbox').innerHTML=h;
 document.getElementById('modal').classList.add('open');
}
async function act(ep,extra){
 let d;
 try{d=await api(ep,extra?Object.assign({token:TOKEN},extra):{token:TOKEN})}catch(e){return}
 toast(d.message||d.error||'Готово');
 if(d.ok){
  const m=d.message||'';
  if(m.indexOf('ДЖЕКПОТ')>=0||m.indexOf('Джекпот')>=0){SND.jackpot();jpShow()}
  else if(m.indexOf('Проигрыш')>=0){SND.lose()}
  else{SND.win();fly()}
  await refresh();
 }else{SND.lose()}
}
function doSpin(){const v=document.getElementById('bet').value;if(!v){toast('Введи ставку');return}act('roulette',{bet:parseInt(v)||0})}
function doPromo(){const v=document.getElementById('promo').value.trim();if(!v){toast('Введи промокод');return}act('promo',{code:v})}
function doTransfer(){const i=document.getElementById('tr_id').value,a=document.getElementById('tr_amt').value;if(!i||!a){toast('Заполни оба поля');return}act('transfer',{to_id:parseInt(i)||0,amount:parseInt(a)||0})}
document.addEventListener('click',function(e){
 const t=e.target;
 let c=t.closest('[data-act]');if(c){SND.click();act(c.dataset.act);return}
 let b=t.closest('[data-buy]');if(b){SND.click();act('buy',{key:b.dataset.buy});closeModal();return}
 let l=t.closest('[data-loc]');if(l){SND.click();act('location',{key:l.dataset.loc});closeModal();return}
 let m=t.closest('[data-modal]');if(m){openModal(m.dataset.modal,+m.dataset.idx);return}
 if(t.closest('[data-close]')){closeModal();return}
 let tb=t.closest('[data-tab]');if(tb){cur=tb.dataset.tab;SND.click();draw();return}
});
const TABS=[["home","⛏️","Добыча"],["bag","🎒","Рюкзак"],["mines","🗺","Шахты"],["shop","🛒","Магазин"],["auto","🤖","Авто"],["quests","🎯","Задания"],["top","🏆","Топ"],["me","👤","Профиль"]];
const PAGES={
home(){
 let h='';
 if(S.location_img)h+='<img class="mine-img" src="'+S.location_img+'" onerror="this.remove()">';
 h+='<div class="card"><b>'+esc(S.location)+'</b> <span class="tag">⛏ '+esc(S.pickaxe)+'</span><br><span class="tag">'+(S.mine_ready?'⛏ Шахта готова ✅':'⏳ Подожди '+S.mine_wait+' сек.')+'</span>';
 h+='<button class="btn g" data-act="mine">⛏ Копать</button>';
 h+='<button class="btn b" data-act="sell">💰 Продать руду ('+S.bag_value+' монет)</button>';
 h+='<button class="btn b" data-act="bonus">🎁 Бонус ('+esc(S.bonus_left)+')</button>';
 h+='<button class="btn b" data-act="case">📦 Открыть кейс</button></div>';
 h+='<div class="card"><h3>🎲 Рулетка</h3><pre>'+esc(S.roulette_info)+'</pre>';
 if(S.roulette_open){h+='<input id="bet" type="number" placeholder="Ставка '+S.roulette_min+'–'+S.roulette_max+'"><button class="btn r" onclick="doSpin()">🎲 Крутить</button>'}else{h+='<p class="tag">🔒 Откроется с '+S.roulette_min_level+' уровня</p>'}
 h+='</div><div class="card"><h3>🎟 Промокод</h3><input id="promo" placeholder="Промокод"><button class="btn b" onclick="doPromo()">Активировать</button></div>';
 h+='<div class="card"><h3>💸 Перевод монет</h3><input id="tr_id" type="number" placeholder="ID игрока"><input id="tr_amt" type="number" placeholder="Сумма"><button class="btn b" onclick="doTransfer()">Перевести</button></div>';
 return h
},
bag(){
 let h='<div class="card"><h3>🎒 Рюкзак</h3><table><tr><th>Руда</th><th>Кол-во</th><th>Цена</th><th>Итого</th></tr>';
 S.backpack.forEach(b=>{if(b.count>0)h+='<tr><td>'+esc(b.name)+'</td><td>'+b.count+'</td><td>'+b.price+'</td><td>'+(b.count*b.price)+'</td></tr>'});
 h+='</table><p class="sum">💰 Всё это стоит '+S.bag_value+' монет</p>';
 h+='<button class="btn g" data-act="sell">💰 Продать всё</button></div>';
 h+='<div class="card"><h3>🧙 Коллекция</h3><p class="tag">Суммарный бонус: <b class="ok">+'+S.char_bonus+'%</b> к добыче</p>';
 S.characters.forEach(c=>{h+='<div class="item" data-modal="char" data-idx="'+S.characters.indexOf(c)+'">'+(c.img?'<img src="'+c.img+'" onerror="this.remove()">':'<div class="ph">🧙</div>')+'<div class="nm"><b>'+esc(c.name)+'</b><small style="color:'+rarc(c.rar)+'">'+c.rar+' • +'+c.bonus+'%</small></div>'+(c.owned?'<span class="ok">есть</span>':'<span class="tag">—</span>')+'</div>'});
 return h+'</div>'
},
mines(){
 let h='<div class="card"><h3>🗺 Локации шахт — тапни для деталей</h3>';
 S.locations.forEach((l,i)=>{
  h+='<div class="item" data-modal="loc" data-idx="'+i+'">'+(l.img?'<img src="'+l.img+'" onerror="this.remove()">':'<div class="ph">🗺</div>');
  h+='<div class="nm"><b>'+esc(l.name)+'</b><small>×'+l.mult+' — '+esc(l.desc)+' (с '+l.level+' ур.)</small></div>';
  if(l.current)h+='<span class="ok">📍</span>';
  else if(l.available)h+='<button class="btn g" style="width:auto;padding:8px 12px;margin:0" data-loc="'+l.key+'">Выбрать</button>';
  else h+='<span class="no">🔒</span>';
  h+='</div>';
 });
 return h+'</div>'
},
shop(){
 let h='<div class="card"><h3>⛏️ Кирки — тапни, чтобы увидеть фото и силу</h3>';
 S.shop.forEach((p,i)=>{
  h+='<div class="item" data-modal="pick" data-idx="'+i+'">'+(p.img?'<img src="'+p.img+'" onerror="this.remove()">':'<div class="ph">⛏️</div>');
  h+='<div class="nm"><b>'+esc(p.name)+'</b><small>Сила '+p.power+' • ур. '+p.level+' • '+p.price+' монет</small></div>';
  h+=p.owned?'<span class="ok">есть</span>':(p.next?'<span class="tag">доступна</span>':'<span class="no">🔒</span>');
  h+='</div>';
 });
 h+='</div><div class="card"><h3>🧙 Персонажи (шанс выпадения при копке ~3%)</h3>';
 S.characters.forEach((c,i)=>{
  h+='<div class="item" data-modal="char" data-idx="'+i+'">'+(c.img?'<img src="'+c.img+'" onerror="this.remove()">':'<div class="ph">🧙</div>');
  h+='<div class="nm"><b>'+esc(c.name)+'</b><small style="color:'+rarc(c.rar)+'">'+c.rar+' • +'+c.bonus+'% • шанс '+c.chance+'%</small></div>';
  h+=(c.owned?'<span class="ok">есть</span>':'<span class="tag">—</span>')+'</div>';
 });
 return h+'</div>'
},
auto(){
 let h='<div class="card"><h3>🤖 Автосбор</h3>';
 if(S.auto_level>0){
  h+='<p>Уровень: <b>'+S.auto_level+'</b></p>';
  h+='<p class="tag">Следующий сбор: '+(S.auto_mins_left===0?'прямо сейчас':'через '+Math.floor(S.auto_mins_left/60)+' ч '+S.auto_mins_left%60+' мин')+'</p>';
 }else{
  h+='<p class="tag">Шахта копает сама каждые 3 часа и присылает руду!</p>';
 }
 if(S.auto_next_price)h+='<button class="btn g" data-act="auto_upgrade">⬆️ Улучшить до ур. '+(S.auto_level+1)+' за '+S.auto_next_price+'</button>';
 else h+='<p class="ok">🏆 Максимальный уровень!</p>';
 return h+'</div>'
},
quests(){
 let h='<div class="card"><h3>🎯 Ежедневные задания</h3>';
 S.quests.items.forEach(q=>{
  h+='<p>'+esc(q.title)+' — <b>'+q.n+'/'+q.goal+'</b> '+(q.n>=q.goal?'<span class="ok">✅</span>':'<span class="tag">⬜</span>')+'</p>';
 });
 h+='<p class="sum">🎁 Награда: '+S.quests.reward+' монет</p>';
 if(S.quests.can_claim)h+='<button class="btn g" data-act="quests">🎁 Забрать награду</button>';
 else h+='<p class="tag">Выполни все задания — и забирай награду. Новые — каждый день!</p>';
 return h+'</div>'
},
top(){
 let h='<div class="card"><h3>💰 Богатейшие</h3><table><tr><th>Игрок</th><th>Монеты</th></tr>';
 S.top_rich.forEach(r=>{h+='<tr><td>'+esc(r[0])+'</td><td>'+r[1]+'</td></tr>'});
 h+='</table></div><div class="card"><h3>🏅 По уровню</h3><table><tr><th>Игрок</th><th>Уровень</th></tr>';
 S.top_level.forEach(r=>{h+='<tr><td>'+esc(r[0])+'</td><td>'+r[1]+'</td></tr>'});
 return h+'</table></div>'
},
me(){
 let h='<div class="card" style="text-align:center">';
 if(S.pickaxe_img)h+='<img class="mbig" src="'+S.pickaxe_img+'" onerror="this.remove()">';
 h+='<h3>👤 '+esc(S.username)+'</h3><pre>'+esc(S.profile)+'</pre></div>';
 return h
}
};
(async function(){
 try{if(tg)tg.expand()}catch(e){}
 if(!TOKEN){await initAuth()}
 if(!TOKEN){noAuthScreen();return}
 refresh()
})();
</script></body></html>"""


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
        check_string = "\\n".join(
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

def auth_body(request, data):
    token = (data.get("token") or request.headers.get("Authorization", "").replace("Bearer ", "")).strip()
    s = SESSIONS.get(token)
    if not s or datetime.now() > s["expires_at"]:
        return None, None
    return get_user(s["user_id"]), token

def err(msg):
    return aio_web.json_response({"ok": False, "error": msg})

def state_payload(user):
    uid = user["user_id"]
    prices = get_prices()
    backpack = [{"key": k, "name": ORES[k]["name"], "count": int(user.get(f"ore_{k}", 0) or 0),
                 "price": prices.get(k, ORES[k]["price"])} for k in ORE_KEYS]
    bag_value = sum(x["count"] * x["price"] for x in backpack)
    pick = PICKAXE_BY_KEY.get(user.get("pickaxe_key", "wood"), PICKAXES[0])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC, level DESC LIMIT 10")
    top_rich = [list(r) for r in cur.fetchall()]
    cur.execute("SELECT username, level FROM users ORDER BY level DESC, balance DESC LIMIT 10")
    top_level = [list(r) for r in cur.fetchall()]
    conn.close()
    if can_bonus(user):
        bonus_left = "доступен"
    else:
        h, m = hours_until_bonus(user)
        bonus_left = f"{h} ч {m} мин"
    loc_key = user.get("location_key") or "mine_1"
    cur_loc = LOCATION_BY_KEY.get(loc_key, LOCATIONS[0])
    locations = [{"key": l["key"], "name": l["name"], "mult": l["mult"], "level": l["level"], "desc": l["desc"],
                  "current": l["key"] == loc_key, "available": user["level"] >= l["level"],
                  "img": img_url(l["key"] + ".jpg")} for l in LOCATIONS]
    auto_lvl = int(user.get("auto_level") or 0)
    mins_left = 0
    if auto_lvl > 0 and user.get("auto_last_at"):
        end = datetime.fromisoformat(user["auto_last_at"]) + timedelta(hours=AUTO_INTERVAL_HOURS)
        mins_left = max(0, int((end - datetime.now()).total_seconds() // 60))
    owned = get_user_characters(uid)
    characters = [{"key": c["key"], "name": c["name"], "bonus": c["bonus"], "chance": c["chance"],
                   "rar": c["rar"], "owned": c["key"] in owned,
                   "img": img_url(CHAR_IMG[c["key"]])} for c in CHARACTERS]
    user_q = quest_refresh(user)
    quests = {"items": [{"title": QUEST_TITLES[k], "n": min(int(user_q.get(f"q_{k}") or 0), g), "goal": g}
                        for k, g in QUEST_GOALS.items()],
              "reward": QUEST_REWARD,
              "can_claim": all(min(int(user_q.get(f"q_{k}") or 0), g) >= g for k, g in QUEST_GOALS.items())
                           and not user_q.get("q_claimed")}
    keys = [p["key"] for p in PICKAXES]
    pidx = keys.index(user.get("pickaxe_key", "wood"))
    shop = [{"key": p["key"], "name": p["name"], "power": p["power"], "price": p["price"], "level": p["level"],
             "owned": i <= pidx, "next": i == pidx + 1, "img": img_url("pick_" + p["key"] + ".jpg")} for i, p in enumerate(PICKAXES)]
    roulette_info = "\\n".join(f"• {s['name']} — {int(s['chance'] * 100)}%" for s in ROULETTE_SECTORS)
    return {
        "ok": True,
        "username": user.get("username", ""),
        "balance": user["balance"], "xp": user["xp"],
        "xp_needed": xp_needed_for_next_level(user["level"]), "level": user["level"],
        "pickaxe": pick["name"], "pickaxe_img": img_url("pick_" + pick["key"] + ".jpg"),
        "backpack": backpack, "bag_value": bag_value,
        "mine_ready": can_mine(user), "mine_wait": seconds_until_mine(user),
        "bonus_ready": can_bonus(user), "bonus_left": bonus_left,
        "case_ready": can_case(user), "case_hours": get_setting("case_hours", CASE_COOLDOWN_HOURS),
        "shop": shop, "top_rich": top_rich, "top_level": top_level,
        "locations": locations, "location": cur_loc["name"], "location_img": img_url(loc_key + ".jpg"),
        "auto_level": auto_lvl, "auto_mins_left": mins_left if auto_lvl > 0 else None,
        "auto_next_price": auto_next_price(auto_lvl) if auto_lvl < AUTO_MAX_LEVEL else None,
        "characters": characters, "char_bonus": min(100, char_bonus_percent(owned)),
        "quests": quests,
        "roulette_open": user["level"] >= ROULETTE_MIN_LEVEL,
        "roulette_min_level": ROULETTE_MIN_LEVEL,
        "roulette_min": ROULETTE_MIN_BET, "roulette_max": ROULETTE_MAX_BET,
        "roulette_info": roulette_info,
        "profile": profile_text(uid),
    }

async def api_state(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла. Получи новый вход: «🖥 Панель» или /panel"}, status=403)
    return aio_web.json_response(state_payload(user))

async def api_mine(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    msg = perform_mine(user["user_id"])
    u = get_user(user["user_id"])
    return aio_web.json_response({"ok": not msg.startswith("Подожди"), "message": msg,
                                  "balance": u["balance"], "level": u["level"]})

async def api_sell(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    msg = perform_sell(user["user_id"])
    u = get_user(user["user_id"])
    return aio_web.json_response({"ok": not msg.startswith("Рюкзак пуст"), "message": msg, "balance": u["balance"]})

async def api_bonus(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    amount, msg = perform_bonus_core(user["user_id"])
    u = get_user(user["user_id"])
    return aio_web.json_response({"ok": amount is not None, "message": msg, "balance": u["balance"]})

async def api_case(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    reward, msg = perform_case(user["user_id"])
    u = get_user(user["user_id"])
    return aio_web.json_response({"ok": reward is not None, "message": msg, "balance": u["balance"]})

async def api_quests(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    ok, msg = claim_quests(user["user_id"])
    u = get_user(user["user_id"])
    return aio_web.json_response({"ok": ok, "message": msg, "balance": u["balance"]})

async def api_roulette(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    if data.get("bet") is None:
        return aio_web.json_response({"ok": True, "message": f"Ставка от {ROULETTE_MIN_BET} до {ROULETTE_MAX_BET} монет"})
    try:
        bet = int(data["bet"])
    except (TypeError, ValueError):
        return err("Ставка — число")
    sector, msg, delta = perform_spin(user["user_id"], bet)
    u = get_user(user["user_id"])
    return aio_web.json_response({"ok": sector is not None, "message": msg, "balance": u["balance"]})

async def api_buy(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    wanted = next((p for p in PICKAXES if p["key"] == data.get("key")), None)
    if not wanted:
        return err("Такой кирки нет")
    keys = [p["key"] for p in PICKAXES]
    if keys.index(wanted["key"]) != keys.index(user.get("pickaxe_key", "wood")) + 1:
        return err("Покупай по порядку")
    if user["level"] < wanted["level"]:
        return err(f"Нужен уровень {wanted['level']}")
    discount, base, jackpot = get_discount(user["user_id"])
    price = int(wanted["price"] * (100 - discount) / 100)
    if user["balance"] < price:
        return err(f"Нужно {price} монет (со скидкой {discount}%), у тебя {user['balance']}")
    update_user(user["user_id"], balance=user["balance"] - price, pickaxe_key=wanted["key"])
    if jackpot:
        consume_jackpot(user["user_id"])
    add_purchase(user["user_id"], wanted["key"], price)
    return aio_web.json_response({"ok": True, "message": f"Куплена кирка: {wanted['name']} за {price} монет!"})

async def api_location(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    loc = next((l for l in LOCATIONS if l["key"] == data.get("key")), None)
    if not loc:
        return err("Такой локации нет")
    if user["level"] < loc["level"]:
        return err(f"«{loc['name']}» откроется с {loc['level']} уровня")
    update_user(user["user_id"], location_key=loc["key"])
    return aio_web.json_response({"ok": True, "message": f"Локация: {loc['name']} ({loc['desc']})"})

async def api_auto_upgrade(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    lvl = int(user.get("auto_level") or 0)
    if lvl >= AUTO_MAX_LEVEL:
        return err("Максимальный уровень автосбора")
    price = auto_next_price(lvl)
    if user["balance"] < price:
        return err(f"Не хватает монет: нужно {price}, у тебя {user['balance']}")
    kwargs = {"balance": user["balance"] - price, "auto_level": lvl + 1}
    if lvl == 0:
        kwargs["auto_last_at"] = datetime.now().isoformat()
    update_user(user["user_id"], **kwargs)
    return aio_web.json_response({"ok": True, "message": f"Автосбор прокачан до уровня {lvl + 1}! Сбор каждые {AUTO_INTERVAL_HOURS} часа."})

async def api_promo(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    code = (data.get("code") or "").strip().upper()
    if not code:
        return err("Введи промокод")
    result, error = redeem_promo(user["user_id"], code)
    if error:
        return err(error)
    ptype, amount = result
    return aio_web.json_response({"ok": True, "message": f"Активирован: +{amount} {PROMO_TYPES.get(ptype, ptype)}"})

async def api_transfer(request):
    data = await request.json()
    user, token = auth_body(request, data)
    if not user:
        return aio_web.json_response({"ok": False, "error": "Сессия истекла"}, status=403)
    try:
        to_id = int(data.get("to_id"))
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        return err("ID и сумма — числа")
    moved, error = transfer_coins(user["user_id"], to_id, amount)
    if error:
        return err(error)
    u = get_user(user["user_id"])
    return aio_web.json_response({"ok": True, "message": f"Переведено {moved} монет игроку {to_id}!", "balance": u["balance"]})

async def img_handler(request):
    name = request.match_info.get("name", "")
    if "/" in name or ".." in name or not name:
        return aio_web.Response(status=404)
    real = find_img_file(name)
    path = os.path.join(IMG_DIR, real)
    if not os.path.exists(path):
        return aio_web.Response(status=404)
    ctype = ("image/png" if real.endswith(".png")
             else "image/webp" if real.endswith(".webp")
             else "image/gif" if real.endswith(".gif")
             else "image/jpeg")
    return aio_web.Response(body=open(path, "rb").read(), content_type=ctype)

async def panel_page(request):
    return aio_web.Response(text=PANEL_PAGE, content_type="text/html")

LANDING_HTML = """<!DOCTYPE html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Анимешная шахта</title>
<style>
*{margin:0;box-sizing:border-box;font-family:'Segoe UI',sans-serif}
html,body{height:100%}
body{display:flex;align-items:center;justify-content:center;background:linear-gradient(-45deg,#0d0d0f,#1a1030,#0d2030,#180d24);background-size:400% 400%;animation:grad 12s ease infinite;color:#fff;overflow:hidden}
@keyframes grad{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.box{text-align:center;padding:24px;z-index:2}
h1{font-size:42px;font-weight:900;margin-bottom:10px;text-shadow:0 0 30px rgba(198,255,0,.4)}
p{color:#9aa3ad;font-size:16px;max-width:340px;margin:0 auto 24px}
.btn{display:inline-block;padding:14px 38px;border-radius:14px;background:#c6ff00;color:#111;font-weight:800;font-size:17px;text-decoration:none;box-shadow:0 0 30px rgba(198,255,0,.35);transition:transform .15s}
.btn:hover{transform:scale(1.05)}
.gem{position:absolute;font-size:26px;opacity:.75;animation:float 6s ease-in-out infinite}
@keyframes float{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-24px) rotate(14deg)}}
</style></head><body>
<span class="gem" style="left:8%;top:18%;animation-delay:0s">💎</span>
<span class="gem" style="left:20%;top:70%;animation-delay:1.2s">🪨</span>
<span class="gem" style="right:12%;top:24%;animation-delay:.6s">⛏️</span>
<span class="gem" style="right:22%;top:74%;animation-delay:1.8s">💎</span>
<span class="gem" style="left:44%;top:10%;animation-delay:2.4s">🟡</span>
<div class="box">
<h1>⛏️ Анимешная шахта</h1>
<p>Копай руду, качай кирки, собирай аниме-персонажей и лови джекпот — всё прямо в Telegram.</p>
{{BOTBTN}}
</div></body></html>"""
ADMIN_PAGE_HTML = """<!DOCTYPE html><html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Админ — Аниме-шахты</title>
<style>
*{margin:0;box-sizing:border-box;font-family:'Segoe UI',sans-serif}
body{background:#0d0d0f;color:#fff;padding:16px}
.card{background:#1a1a1e;border-radius:16px;margin:10px 0;padding:14px}
h3{margin-bottom:8px}h1{font-size:22px;margin:6px 0}
input{width:100%;padding:10px;border-radius:8px;border:none;background:#24242a;color:#fff;font-size:15px;margin-top:6px}
.btn{width:100%;padding:11px;border:none;border-radius:12px;font-weight:700;font-size:15px;cursor:pointer;margin-top:8px}
.g{background:#c6ff00;color:#111}.b{background:#2d6cdf;color:#fff}.gr{background:#333;color:#999}
.tag{color:#8b8b95;font-size:13px}.ok{color:#c6ff00}.no{color:#ff6b6b}
table{width:100%;border-collapse:collapse}th,td{padding:5px 4px;text-align:left;border-bottom:1px solid #2a2a2e;font-size:13px}th{color:#999}
#msg{margin-top:10px;min-height:22px;font-weight:700}
select{width:100%;padding:10px;border-radius:8px;border:none;background:#24242a;color:#fff;font-size:15px;margin-top:6px}
</style></head><body>
<h1>⚙️ Админ-панель</h1>
<div class="card"><input id="tok" placeholder="Токен админа" type="password"><button class="btn g" onclick="saveTok()">Войти</button></div>
<div class="card"><h3>📊 Статистика</h3><div id="stats" class="tag">—</div></div>
<div class="card"><h3>👥 Выдать игроку</h3>
<input id="g_id" type="number" placeholder="ID игрока">
<select id="g_field"><option value="coins">Монеты</option><option value="xp">Опыт</option><option value="level">Уровень</option><option value="stone">🪨 Камень</option><option value="iron">⚪ Железо</option><option value="copper">🟤 Медь</option><option value="silver">⚪ Серебро</option><option value="gold">🟡 Золото</option><option value="ruby">🔴 Рубины</option><option value="diamond">💎 Алмазы</option><option value="mithril">🔮 Мифрил</option></select>
<input id="g_val" type="number" placeholder="Количество">
<button class="btn b" onclick="give()">Выдать</button></div>
<div class="card"><h3>🎟 Промокод</h3>
<input id="p_code" placeholder="КОД">
<select id="p_type"><option value="money">Монеты</option><option value="xp">Опыт</option><option value="stone">Камень</option><option value="iron">Железо</option><option value="copper">Медь</option><option value="silver">Серебро</option><option value="gold">Золото</option><option value="ruby">Рубины</option><option value="diamond">Алмазы</option><option value="mithril">Мифрил</option></select>
<input id="p_amt" type="number" placeholder="Количество">
<input id="p_uses" type="number" placeholder="Активаций" value="10">
<button class="btn b" onclick="genpromo()">Создать</button></div>
<div class="card"><h3>📣 Рассылка всем</h3>
<textarea id="b_text" rows="3" style="width:100%;padding:10px;border-radius:8px;border:none;background:#24242a;color:#fff;font-size:15px" placeholder="Текст рассылки"></textarea>
<button class="btn r" onclick="broadcast()">Разослать</button></div>
<div class="card"><h3>🏆 Топ-50 игроков</h3><div id="users">—</div></div>
<div id="msg"></div>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script>
let TOK=localStorage.getItem('shaxty_admin')||'';
document.getElementById('tok').value=TOK;
function saveTok(){TOK=document.getElementById('tok').value.trim();localStorage.setItem('shaxty_admin',TOK);loadAll()}
function msg(m,ok){document.getElementById('msg').innerHTML=(ok?'<span class="ok">':'<span class="no">')+m+'</span>'}
async function adm(ep,body){
 const r=await fetch('/api/admin/'+ep,{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Token':TOK},body:JSON.stringify(body||{})});
 if(r.status===403){msg('Неверный токен',false);throw new Error('auth')}
 return await r.json();
}
async function loadAll(){
 try{
  const s=await adm('stats');
  document.getElementById('stats').innerHTML='Игроков: <b>'+s.players+'</b> • Монет у всех: <b>'+s.coins+'</b> • Покупок: <b>'+s.purchases+'</b> • Промокодов: <b>'+s.promos+'</b> • Автосбор: <b>'+s.autos+'</b>';
  const u=await adm('users');
  let h='<table><tr><th>ID</th><th>Игрок</th><th>Монеты</th><th>Ур.</th></tr>';
  u.users.forEach(x=>{h+='<tr><td>'+x[0]+'</td><td>'+String(x[1]).replace(/</g,'&lt;')+'</td><td>'+x[2]+'</td><td>'+x[3]+'</td></tr>'});
  document.getElementById('users').innerHTML=h+'</table>';
 }catch(e){}
}
async function give(){const d=await adm('give',{user_id:+document.getElementById('g_id').value,field:document.getElementById('g_field').value,value:+document.getElementById('g_val').value});msg(d.message||d.error||'Готово',d.ok);if(d.ok)loadAll()}
async function genpromo(){const d=await adm('genpromo',{code:document.getElementById('p_code').value.trim(),ptype:document.getElementById('p_type').value,amount:+document.getElementById('p_amt').value,uses:+document.getElementById('p_uses').value});msg(d.message||d.error||'Готово',d.ok);if(d.ok)loadAll()}
async function broadcast(){if(!confirm('Разослать ВСЕМ игрокам?'))return;const d=await adm('broadcast',{text:document.getElementById('b_text').value.trim()});msg(d.message||d.error||'Готово',d.ok)}
if(TOK)loadAll();
</script></body></html>"""
# ================= ЛЕНДИНГ (любой неизвестный адрес) =================
async def landing_page(request):
    uname = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
    btn = ""
    if uname:
        btn = '<a class="btn" href="https://t.me/' + uname + '">🎮 Открыть бота</a>'
    return aio_web.Response(text=LANDING_HTML.replace("{{BOTBTN}}", btn), content_type="text/html")

# ================= ВЕБ-АДМИНКА /admin =================
def admin_auth(request, data=None):
    tok = (request.headers.get("X-Admin-Token") or ((data or {}).get("token") or "")).strip()
    return bool(tok) and tok == ADMIN_TOKEN

async def admin_page(request):
    return aio_web.Response(text=ADMIN_PAGE_HTML, content_type="text/html")

async def api_admin_stats(request):
    data = await request.json()
    if not admin_auth(request, data):
        return aio_web.json_response({"ok": False}, status=403)
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(SUM(balance),0) FROM users")
    n, total = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM purchase_history")
    purchases = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM promos")
    promos = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE auto_level > 0")
    autos = cur.fetchone()[0]
    conn.close()
    return aio_web.json_response({"ok": True, "players": n, "coins": total, "purchases": purchases, "promos": promos, "autos": autos})

async def api_admin_give(request):
    data = await request.json()
    if not admin_auth(request, data):
        return aio_web.json_response({"ok": False}, status=403)
    try:
        uid = int(data.get("user_id") or 0)
        val = int(data.get("value") or 0)
    except (TypeError, ValueError):
        return err("ID и количество — числа")
    field = data.get("field") or ""
    u = get_user(uid)
    if not u:
        return err("Игрок с таким ID не найден")
    ADMIN_FIELD_MAP = {
        "coins": "balance", "level": "level", "stone": "ore_stone", "iron": "ore_iron",
        "copper": "ore_copper", "silver": "ore_silver", "gold": "ore_gold",
        "ruby": "ore_ruby", "diamond": "ore_diamond", "mithril": "ore_mithril",
    }
    if field == "xp":
        add_xp_and_level_up(uid, u, val)
        return aio_web.json_response({"ok": True, "message": f"Выдано {val} опыта игроку {uid}"})
    if field not in ADMIN_FIELD_MAP:
        return err("Неизвестное поле")
    col = ADMIN_FIELD_MAP[field]
    new_val = max(0, int(u.get(col, 0) or 0) + val)
    update_user(uid, **{col: new_val})
    return aio_web.json_response({"ok": True, "message": f"Игроку {uid}: {field} = {new_val}"})

async def api_admin_genpromo(request):
    data = await request.json()
    if not admin_auth(request, data):
        return aio_web.json_response({"ok": False}, status=403)
    code = (data.get("code") or "").strip().upper()
    ptype = (data.get("ptype") or "money").strip()
    amount = int(data.get("amount") or 0)
    uses = int(data.get("uses") or 1)
    if not code:
        return err("Придумай код промокода")
    if ptype not in PROMO_TYPES:
        return err("Тип: " + ", ".join(PROMO_TYPES))
    create_promo(code, ptype, amount, uses)
    return aio_web.json_response({"ok": True, "message": f"Промокод {code}: {amount} {PROMO_TYPES[ptype]}, активаций {uses}"})

async def api_admin_broadcast(request):
    data = await request.json()
    if not admin_auth(request, data):
        return aio_web.json_response({"ok": False}, status=403)
    text = (data.get("text") or "").strip()
    if not text:
        return err("Пустой текст рассылки")
    BROADCAST_QUEUE.append(text)
    return aio_web.json_response({"ok": True, "message": "Рассылка поставлена в очередь"})

async def api_admin_users(request):
    data = await request.json()
    if not admin_auth(request, data):
        return aio_web.json_response({"ok": False}, status=403)
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT user_id, username, balance, level FROM users ORDER BY balance DESC LIMIT 50")
    rows = [list(r) for r in cur.fetchall()]
    conn.close()
    return aio_web.json_response({"ok": True, "users": rows})

async def broadcast_worker():
    while True:
        try:
            if not BROADCAST_QUEUE:
                await asyncio.sleep(2)
                continue
            text = BROADCAST_QUEUE.pop(0)
            conn = get_conn(); cur = conn.cursor()
            cur.execute("SELECT user_id FROM users")
            ids = [r[0] for r in cur.fetchall()]
            conn.close()
            for uid in ids:
                try:
                    await bot.send_message(uid, text)
                except Exception:
                    pass
                await asyncio.sleep(0.05)
        except Exception:
            await asyncio.sleep(2)

def run_web():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = aio_web.Application()
    app.router.add_get("/", index_page)
    app.router.add_get("/panel", panel_page)
    app.router.add_get("/app", panel_page)
    app.router.add_get("/admin", admin_page)
    app.router.add_post("/api/admin/stats", api_admin_stats)
    app.router.add_post("/api/admin/give", api_admin_give)
    app.router.add_post("/api/admin/genpromo", api_admin_genpromo)
    app.router.add_post("/api/admin/broadcast", api_admin_broadcast)
    app.router.add_post("/api/admin/users", api_admin_users)
    app.router.add_post("/api/login", api_login)
    app.router.add_post("/api/tg_auth", api_tg_auth)
    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/mine", api_mine)
    app.router.add_post("/api/sell", api_sell)
    app.router.add_post("/api/bonus", api_bonus)
    app.router.add_post("/api/case", api_case)
    app.router.add_post("/api/quests", api_quests)
    app.router.add_post("/api/roulette", api_roulette)
    app.router.add_post("/api/buy", api_buy)
    app.router.add_post("/api/location", api_location)
    app.router.add_post("/api/auto_upgrade", api_auto_upgrade)
    app.router.add_post("/api/promo", api_promo)
    app.router.add_post("/api/transfer", api_transfer)
    app.router.add_get("/img/{name}", img_handler)
    app.router.add_get("/{tail:.*}", landing_page)
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
    asyncio.create_task(broadcast_worker()) # рассылка из админки
    try:
        me = await bot.get_me()
        if me and me.username:
            os.environ["BOT_USERNAME"] = me.username
    except Exception:
        pass
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
