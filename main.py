# -*- coding: utf-8 -*-
# Mining bot: Telegram Mini App (/app) + чат-команды. Один файл.
import asyncio, os, json, hmac, hashlib, random, sqlite3, threading, time, base64, re
from urllib.parse import parse_qsl
from aiohttp import web as aio_web
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BufferedInputFile

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN", "")
APP_URL = os.getenv("APP_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))
ADMIN_IDS = {5636309834}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
IMG_DIR = os.path.join(BASE_DIR, "images")
AVATAR_DIR = os.path.join(DATA_DIR, "avatars")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(AVATAR_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "bot_db.sqlite")
_db_lock = threading.Lock()

# ================= ИГРА =================
ENERGY_MAX = 10
ENERGY_REGEN_MIN = 30
ENERGY_REFILL_PRICE = 2500
ROULETTE_MIN_LEVEL = 20
ROULETTE_MIN_BET = 10
ROULETTE_SECTORS = [(0.0, 40.0), (1.1, 30.0), (1.5, 15.0), (2.0, 10.0), (3.0, 4.0), (10.0, 1.0)]

BONUS_CD_H = 12
CASE_CD_H = 24
CHAR_DROP_BONUS = 4.0
CHAR_DROP_CASE = 8.0
REFUND_WINDOW_MIN = 15
TRANSFER_FEE = 0.05
AUTO_INTERVAL_H = 3
AUTO_MAX_LEVEL = 10
CHAR_DROP_MINE = 3.0

ORES = {
    "stone":   {"name": "🪨 Камень",        "price": 3,    "xp": 2},
    "iron":    {"name": "⚪ Железная руда", "price": 12,   "xp": 5},
    "copper":  {"name": "🟤 Медная руда",   "price": 35,   "xp": 10},
    "silver":  {"name": "⚪ Серебро",       "price": 95,   "xp": 15},
    "gold":    {"name": "🟡 Золотая руда",  "price": 260,  "xp": 25},
    "ruby":    {"name": "🔴 Рубин",         "price": 650,  "xp": 40},
    "diamond": {"name": "💎 Алмаз",         "price": 1600, "xp": 70},
    "mithril": {"name": "🔮 Мифрил",        "price": 4200, "xp": 120},
}
ORE_KEYS = list(ORES.keys())

PICKAXES = [
    {"key": "wood",      "name": "🪵 Деревянная",  "power": 0,   "price": 0,         "level": 1},
    {"key": "stone",     "name": "⛏️ Каменная",    "power": 3,   "price": 1200,      "level": 5},
    {"key": "iron",      "name": "⛏️ Железная",    "power": 10,  "price": 8000,      "level": 15},
    {"key": "gold",      "name": "⛏️ Золотая",     "power": 25,  "price": 45000,     "level": 30},
    {"key": "diamond",   "name": "⛏️ Алмазная",    "power": 50,  "price": 180000,    "level": 50},
    {"key": "mithril",   "name": "⛏️ Мифриловая",  "power": 80,  "price": 700000,    "level": 70},
    {"key": "ruby",      "name": "⛏️ Рубиновая",   "power": 110, "price": 3000000,   "level": 85},
    {"key": "legendary", "name": "⛏️ ЛЕГЕНДАРНАЯ", "power": 150, "price": 12000000,  "level": 100},
]
PICKAXE_BY_KEY = {p["key"]: p for p in PICKAXES}
PICK_DROPS = {
    "wood":      [("stone", 100)],
    "stone":     [("stone", 65), ("iron", 28), ("copper", 7)],
    "iron":      [("stone", 38), ("iron", 35), ("copper", 20), ("silver", 7)],
    "gold":      [("iron", 30), ("copper", 30), ("silver", 24), ("gold", 11), ("ruby", 5)],
    "diamond":   [("copper", 20), ("silver", 30), ("gold", 26), ("ruby", 15), ("diamond", 9)],
    "mithril":   [("silver", 20), ("gold", 30), ("ruby", 25), ("diamond", 18), ("mithril", 7)],
    "ruby":      [("gold", 25), ("ruby", 30), ("diamond", 25), ("mithril", 17), ("silver", 3)],
    "legendary": [("gold", 15), ("ruby", 25), ("diamond", 30), ("mithril", 28), ("silver", 2)],
}

CHARACTERS = [
    {"key": "podrugi", "name": "👧 Подруги",           "bonus": 5,   "chance": 40,   "rar": "обычный"},
    {"key": "kazuya",  "name": "👦 Казуя",             "bonus": 15,  "chance": 30,   "rar": "обычный"},
    {"key": "minu",    "name": "🍇 Мину Минета",       "bonus": 10,  "chance": 25,   "rar": "обычный"},
    {"key": "usopp",   "name": "🎯 Усопп",             "bonus": 8,   "chance": 20,   "rar": "обычный"},
    {"key": "shinji",  "name": "🎧 Синдзи",            "bonus": 7,   "chance": 15,   "rar": "обычный"},
    {"key": "mumen",   "name": "🚴 Мумен Райдер",      "bonus": 20,  "chance": 10,   "rar": "редкий"},
    {"key": "tenten",  "name": "⚔️ Тен Тен",           "bonus": 25,  "chance": 8,    "rar": "редкий"},
    {"key": "buggy",   "name": "🤡 Багги",             "bonus": 28,  "chance": 6,    "rar": "редкий"},
    {"key": "yukiteru","name": "📱 Юкитэру Амано",     "bonus": 30,  "chance": 5,    "rar": "редкий"},
    {"key": "kazuma",  "name": "💧 Кадзума Сато",      "bonus": 35,  "chance": 4,    "rar": "редкий"},
    {"key": "luffy",   "name": "👒 Луффи",             "bonus": 55,  "chance": 2,    "rar": "эпический"},
    {"key": "jinwoo",  "name": "🗡️ Сон Джин Ву",      "bonus": 40,  "chance": 3,    "rar": "эпический"},
    {"key": "king",    "name": "👑 Кинг",              "bonus": 45,  "chance": 2.5,  "rar": "эпический"},
    {"key": "lelouch", "name": "♟️ Лелуш ви Британия", "bonus": 75,  "chance": 1,    "rar": "легендарный"},
    {"key": "monoma",  "name": "📝 Нейто Монома",      "bonus": 60,  "chance": 1.5,  "rar": "легендарный"},
    {"key": "reigen",  "name": "🌀 Рейген",            "bonus": 65,  "chance": 1.2,  "rar": "легендарный"},
    {"key": "ichigo",  "name": "🗡️ Ичиго",            "bonus": 85,  "chance": 0.5,  "rar": "мифический"},
    {"key": "kurapika","name": "⛓️ Курапика",          "bonus": 80,  "chance": 0.8,  "rar": "мифический"},
    {"key": "killua",  "name": "⚡ Киллуа",            "bonus": 82,  "chance": 0.6,  "rar": "мифический"},
    {"key": "gojo",    "name": "🕶️ Годжо",            "bonus": 100, "chance": 0.3,  "rar": "мифический"},
    {"key": "adam",    "name": "👊 Адам",              "bonus": 90,  "chance": 0.4,  "rar": "мифический"},
    {"key": "simon",   "name": "⛏️ Симон",             "bonus": 110, "chance": 0.2,  "rar": "уникальный"},
    {"key": "alucard", "name": "🧛 Алукард",           "bonus": 130, "chance": 0.15, "rar": "уникальный"},
    {"key": "mob",     "name": "🌫️ Моб",               "bonus": 150, "chance": 0.1,  "rar": "уникальный"},
]
CHAR_BY_KEY = {c["key"]: c for c in CHARACTERS}
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

LOCATIONS = [
    {"key": "mine_1", "name": "🪨 Обычная шахта",      "level": 1,  "mult": 1.0, "desc": "базовая добыча"},
    {"key": "mine_2", "name": "🕳 Глубокая шахта",     "level": 15, "mult": 1.5, "desc": "все руды ×1,5"},
    {"key": "mine_3", "name": "🔥 Огненная пропасть",  "level": 30, "mult": 2.0, "desc": "все руды ×2,0"},
    {"key": "mine_4", "name": "❄️ Ледяные гроты",      "level": 45, "mult": 2.5, "desc": "все руды ×2,5"},
    {"key": "mine_5", "name": "✨ Зачарованные копи",  "level": 60, "mult": 3.0, "desc": "все руды ×3,0"},
    {"key": "mine_6", "name": "💎 Мифриловые глубины", "level": 80, "mult": 4.0, "desc": "все руды ×4,0"},
]
LOCATION_BY_KEY = {l["key"]: l for l in LOCATIONS}

QUESTS = [
    {"key": "dig50",  "name": "Накопать 50 раз",            "event": "mine",  "target": 50,   "money": 2000, "xp": 300},
    {"key": "spin25", "name": "Крутить рулетку 25 раз",     "event": "spin",  "target": 25,   "money": 3000, "xp": 300},
    {"key": "sell5k", "name": "Продать руды на 5000 монет", "event": "sell",  "target": 5000, "money": 4000, "xp": 400},
    {"key": "case3",  "name": "Открыть 3 кейса",            "event": "case",  "target": 3,    "money": 2500, "xp": 250},
    {"key": "bonus2", "name": "Забрать бонус 2 раза",       "event": "bonus", "target": 2,    "money": 1500, "xp": 200},
]
QUEST_BY_KEY = {q["key"]: q for q in QUESTS}

EMOJI_AVATARS = ["⛏️", "💎", "🔥", "👑", "🚀", "🎩", "🦊", "🐸", "🐲", "🤖", "🌟", "🧙", "🥷", "🗿", "💀", "🍀"]

# ================= БАЗА =================
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
 user_id INTEGER PRIMARY KEY,
 name TEXT DEFAULT '',
 money INTEGER DEFAULT 1000,
 xp INTEGER DEFAULT 0,
 energy INTEGER DEFAULT 10,
 energy_ts INTEGER DEFAULT 0,
 pickaxe TEXT DEFAULT 'wood',
 location TEXT DEFAULT 'mine_1',
 char_key TEXT DEFAULT '',
 bonus_ts INTEGER DEFAULT 0,
 case_ts INTEGER DEFAULT 0,
 auto_level INTEGER DEFAULT 0,
 auto_ts INTEGER DEFAULT 0,
 avatar_mode TEXT DEFAULT 'tg',
 avatar_emoji TEXT DEFAULT '⛏️',
 images_on INTEGER DEFAULT 1,
 lp_type TEXT DEFAULT '',
 lp_key TEXT DEFAULT '',
 lp_price INTEGER DEFAULT 0,
 lp_ts INTEGER DEFAULT 0,
 discount_pct INTEGER DEFAULT 0,
 discount_ts INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bag(user_id INTEGER, ore TEXT, qty INTEGER, PRIMARY KEY(user_id, ore));
CREATE TABLE IF NOT EXISTS chars(user_id INTEGER, char_key TEXT, ts INTEGER, PRIMARY KEY(user_id, char_key));
CREATE TABLE IF NOT EXISTS quests(user_id INTEGER, qkey TEXT, p INTEGER DEFAULT 0, claimed INTEGER DEFAULT 0, PRIMARY KEY(user_id, qkey));
CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, uses INTEGER, kind TEXT, value INTEGER);
"""

def db():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _db_lock, db() as c:
        c.executescript(SCHEMA)
        # миграция старых баз: добавить отсутствующие колонки
        cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        wanted = {"name","money","xp","energy","energy_ts","pickaxe","location","char_key",
                  "bonus_ts","case_ts","auto_level","auto_ts","avatar_mode","avatar_emoji",
                  "images_on","lp_type","lp_key","lp_price","lp_ts","discount_pct","discount_ts"}
        for col in wanted - cols:
            try:
                c.execute("ALTER TABLE users ADD COLUMN %s" % col)
            except sqlite3.OperationalError:
                pass

def _default_user(uid, name=""):
    return {"user_id": uid, "name": name or str(uid), "money": 1000, "xp": 0,
            "energy": ENERGY_MAX, "energy_ts": int(time.time()), "pickaxe": "wood",
            "location": "mine_1", "char_key": "", "bonus_ts": 0, "case_ts": 0,
            "auto_level": 0, "auto_ts": 0, "avatar_mode": "tg", "avatar_emoji": "⛏️",
            "images_on": 1, "lp_type": "", "lp_key": "", "lp_price": 0, "lp_ts": 0,
            "discount_pct": 0, "discount_ts": 0}

def get_user(uid, name=""):
    with _db_lock, db() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if row is None:
            d = _default_user(uid, name)
            c.execute("INSERT INTO users(user_id, name, energy_ts) VALUES(?,?,?)", (uid, d["name"], d["energy_ts"]))
            return d
        u = dict(row)
        # пересчёт энергии
        now = int(time.time())
        step = ENERGY_REGEN_MIN * 60
        passed = (now - (u["energy_ts"] or now)) // step
        if passed > 0 and u["energy"] < ENERGY_MAX:
            u["energy"] = min(ENERGY_MAX, u["energy"] + passed)
        u["energy_ts"] = now
        c.execute("UPDATE users SET energy=?, energy_ts=?, name=CASE WHEN ?<>'' THEN ? ELSE name END WHERE user_id=?",
                  (u["energy"], u["energy_ts"], name or "", name or u["name"], uid))
        return u

def save_user(u):
    with _db_lock, db() as c:
        keys = [k for k in u.keys() if k != "user_id"]
        c.execute("UPDATE users SET %s WHERE user_id=?" % ",".join(k+"=?" for k in keys),
                  [u[k] for k in keys] + [u["user_id"]])

def level_of(xp):
    lvl, rest = 1, xp
    need = 100
    while rest >= need and lvl < 100:
        rest -= need
        lvl += 1
        need = 100 * lvl
    return lvl

def level_progress(xp):
    lvl, rest = 1, xp
    need = 100
    while rest >= need and lvl < 100:
        rest -= need
        lvl += 1
        need = 100 * lvl
    return lvl, rest, need

def fm(n):
    return f"{int(n):,}".replace(",", " ")

def bag_get(uid):
    with _db_lock, db() as c:
        return {r["ore"]: r["qty"] for r in c.execute("SELECT ore, qty FROM bag WHERE user_id=?", (uid,))}

def bag_add(uid, ore, qty):
    with _db_lock, db() as c:
        c.execute("INSERT INTO bag(user_id, ore, qty) VALUES(?,?,?) ON CONFLICT(user_id, ore) DO UPDATE SET qty=qty+?", (uid, ore, qty, qty))

def quests_add(uid, event, amount=1):
    with _db_lock, db() as c:
        for q in QUESTS:
            if q["event"] == event:
                c.execute("INSERT INTO quests(user_id,qkey,p,claimed) VALUES(?,?,?,0) ON CONFLICT(user_id,qkey) DO UPDATE SET p=p+?",
                          (uid, q["key"], amount, amount))

def quests_state(uid):
    with _db_lock, db() as c:
        rows = {r["qkey"]: dict(r) for r in c.execute("SELECT * FROM quests WHERE user_id=?", (uid,))}
    out = []
    for q in QUESTS:
        st = rows.get(q["key"], {"p": 0, "claimed": 0})
        out.append({"key": q["key"], "name": q["name"], "p": min(st["p"], q["target"]),
                    "target": q["target"], "claimed": st["claimed"], "money": q["money"], "xp": q["xp"]})
    return out

def roll_ore(pick_key):
    drops = PICK_DROPS.get(pick_key, PICK_DROPS["wood"])
    total = sum(w for _, w in drops)
    r = random.random() * total
    acc = 0
    for ore, w in drops:
        acc += w
        if r <= acc:
            return ore
    return drops[-1][0]

def roll_char():
    total = sum(c["chance"] for c in CHARACTERS)
    r = random.random() * total
    acc = 0
    for c in CHARACTERS:
        acc += c["chance"]
        if r <= acc:
            return c["key"]
    return CHARACTERS[0]["key"]

def have_char(uid, key):
    with _db_lock, db() as c:
        return c.execute("SELECT 1 FROM chars WHERE user_id=? AND char_key=?", (uid, key)).fetchone() is not None

def add_char(uid, key):
    if not get_char(key):
        return False
    with _db_lock, db() as c:
        c.execute("INSERT OR IGNORE INTO chars(user_id, char_key, ts) VALUES(?,?,?)", (uid, key, int(time.time())))
    return True

def price_with_discount(u, price):
    if u["discount_pct"] and (u["discount_ts"] or 0) > int(time.time()):
        return int(price * (100 - u["discount_pct"]) / 100)
    return price

# ================= ДЕЙСТВИЯ =================
def do_mine(u):
    if u["energy"] <= 0:
        return {"err": "Нет зарядов энергии. Восстанови в магазине или подожди %d мин." % ENERGY_REGEN_MIN}
    loc = LOCATION_BY_KEY.get(u["location"], LOCATIONS[0])
    pick = PICKAXE_BY_KEY.get(u["pickaxe"], PICKAXES[0])
    u["energy"] -= 1
    ore = roll_ore(pick["key"])
    qty = random.randint(1, 2) + pick["power"] // 30
    char = get_char(u["char_key"]) if u["char_key"] else None
    bonus = char["bonus"] if char else 0
    qty = max(1, int(qty * loc["mult"] * (1 + bonus / 100)))
    bag_add(u["user_id"], ore, qty)
    xp_gain = int(ORES[ore]["xp"] * loc["mult"] * (1 + bonus / 100) * max(1, qty // 2))
    u["xp"] += xp_gain
    save_user(u)
    quests_add(u["user_id"], "mine")
    found = None
    if random.random() * 100 < CHAR_DROP_MINE:
        key = roll_char()
        if not have_char(u["user_id"], key):
            add_char(u["user_id"], key)
            found = CHAR_BY_KEY[key]
    return {"ok": True, "ore": ORES[ore]["name"], "qty": qty, "xp": xp_gain,
            "char": ({"key": found["key"], "name": found["name"], "rar": found["rar"]} if found else None)}

def spin_roulette(u, bet):
    if level_of(u["xp"]) < ROULETTE_MIN_LEVEL:
        return {"err": "Рулетка с %d уровня" % ROULETTE_MIN_LEVEL}
    bet = int(bet)
    if bet < ROULETTE_MIN_BET:
        return {"err": "Минимальная ставка %d" % ROULETTE_MIN_BET}
    if u["money"] < bet:
        return {"err": "Не хватает монет"}
    r = random.random() * 100
    acc, mult = 0, ROULETTE_SECTORS[0][0]
    for m, ch in ROULETTE_SECTORS:
        acc += ch
        if r <= acc:
            mult = m
            break
    payout = int(bet * mult)
    u["money"] += payout - bet
    save_user(u)
    quests_add(u["user_id"], "spin")
    return {"ok": True, "mult": mult, "payout": payout, "bet": bet}

def rand_ore_pack():
    tiers = {"stone": 0, "iron": 1, "copper": 2, "silver": 3, "gold": 4, "ruby": 5, "diamond": 6, "mithril": 7}
    tier = random.choices([0, 1, 2, 3, 4, 5, 6, 7], weights=[35, 25, 18, 10, 7, 3, 1.5, 0.5])[0]
    ores = [k for k, t in tiers.items() if t == tier]
    ore = random.choice(ores)
    return ore, random.randint(3, 10)

def grant_char_drop(u, chance):
    if random.random() * 100 >= chance:
        return None
    key = roll_char()
    if have_char(u["user_id"], key):
        return None
    add_char(u["user_id"], key)
    c = CHAR_BY_KEY[key]
    return {"key": key, "name": c["name"], "rar": c["rar"]}

def claim_bonus(u):
    now = int(time.time())
    if now - (u["bonus_ts"] or 0) < BONUS_CD_H * 3600:
        return {"err": "Бонус будет через %s" % fmt_left(BONUS_CD_H * 3600 - (now - u["bonus_ts"]))}
    u["bonus_ts"] = now
    r = random.random() * 100
    if r < CHAR_DROP_BONUS:
        ch = grant_char_drop(u, 100.0)
        msg = "Персонаж!"
        save_user(u)
        quests_add(u["user_id"], "bonus")
        return {"ok": True, "kind": "char", "char": ch, "text": "🎉 Выбил персонажа: %s!" % ch["name"]}
    if r < 40:
        m = random.randint(300, 3000)
        u["money"] += m
        text = "🪙 Монеты: +%d" % m
    elif r < 60:
        x = random.randint(50, 500)
        u["xp"] += x
        text = "✨ Опыт: +%d" % x
    elif r < 80:
        ore, q = rand_ore_pack()
        bag_add(u["user_id"], ore, q)
        text = "%s ×%d" % (ORES[ore]["name"], q)
    else:
        pct = random.choice([25, 50])
        u["discount_pct"] = pct
        u["discount_ts"] = now + 24 * 3600
        text = "🏷 Скидка %d%% на следующую покупку" % pct
    save_user(u)
    quests_add(u["user_id"], "bonus")
    return {"ok": True, "kind": "reward", "text": text}

def open_case(u):
    now = int(time.time())
    if now - (u["case_ts"] or 0) < CASE_CD_H * 3600:
        return {"err": "Кейс будет через %s" % fmt_left(CASE_CD_H * 3600 - (now - u["case_ts"]))}
    u["case_ts"] = now
    r = random.random() * 100
    if r < CHAR_DROP_CASE:
        ch = grant_char_drop(u, 100.0)
        save_user(u)
        quests_add(u["user_id"], "case")
        return {"ok": True, "kind": "char", "char": ch, "text": "🎉 Из кейса выпал персонаж: %s!" % ch["name"]}
    if r < 50:
        m = max(100, min(100000, int(100 * (1000 ** random.random()))))
        u["money"] += m
        text = "🪙 Монеты: +%d" % m
    elif r < 70:
        x = random.randint(100, 1000)
        u["xp"] += x
        text = "✨ Опыт: +%d" % x
    elif r < 85:
        ore, q = rand_ore_pack()
        bag_add(u["user_id"], ore, q)
        text = "%s ×%d" % (ORES[ore]["name"], q)
    else:
        pct = random.choice([25, 50])
        u["discount_pct"] = pct
        u["discount_ts"] = now + 24 * 3600
        text = "🏷 Скидка %d%% на следующую покупку" % pct
    save_user(u)
    quests_add(u["user_id"], "case")
    return {"ok": True, "kind": "reward", "text": text}

def buy_pickaxe(u, key):
    p = PICKAXE_BY_KEY.get(key)
    if not p:
        return {"err": "Нет такой кирки"}
    if level_of(u["xp"]) < p["level"]:
        return {"err": "Нужен %d уровень" % p["level"]}
    order = [x["key"] for x in PICKAXES]
    if order.index(key) <= order.index(u["pickaxe"]):
        return {"err": "Эта кирка не лучше текущей"}
    price = price_with_discount(u, p["price"])
    if u["money"] < price:
        return {"err": "Не хватает монет (нужно %s)" % fm(price)}
    u["money"] -= price
    u["pickaxe"] = key
    u["discount_pct"] = 0
    u["lp_type"], u["lp_key"], u["lp_price"], u["lp_ts"] = "pick", key, p["price"], int(time.time())
    save_user(u)
    return {"ok": True, "name": p["name"], "price": price}

def buy_auto(u):
    if u["auto_level"] >= AUTO_MAX_LEVEL:
        return {"err": "Максимальный уровень автосбора"}
    price = 5000 * (2 ** u["auto_level"])
    price = price_with_discount(u, price)
    if u["money"] < price:
        return {"err": "Не хватает монет (нужно %s)" % fm(price)}
    u["money"] -= price
    u["auto_level"] += 1
    if u["auto_level"] == 1:
        u["auto_ts"] = int(time.time())
    u["discount_pct"] = 0
    u["lp_type"], u["lp_key"], u["lp_price"], u["lp_ts"] = "auto", "auto", price, int(time.time())
    save_user(u)
    return {"ok": True, "level": u["auto_level"]}

def collect_auto(u):
    if u["auto_level"] <= 0:
        return {"err": "Автосбор ещё не куплен"}
    now = int(time.time())
    waited = now - (u["auto_ts"] or now)
    cycles = int(waited // (AUTO_INTERVAL_H * 3600))
    if cycles <= 0:
        return {"err": "Шахта ещё копает, ждать %s" % fmt_left(AUTO_INTERVAL_H * 3600 - waited)}
    u["auto_ts"] = now
    got = {}
    for _ in range(cycles * (u["auto_level"] * 2)):
        ore = roll_ore(u["pickaxe"])
        got[ore] = got.get(ore, 0) + 1
    for ore, q in got.items():
        bag_add(u["user_id"], ore, q)
    save_user(u)
    return {"ok": True, "got": got, "cycles": cycles}

def sell_ores(u, ore=None, qty=None):
    bag = bag_get(u["user_id"])
    if ore:
        if ore not in ORES or ore not in bag:
            return {"err": "Нет такой руды"}
        q = bag[ore] if (qty in (None, "all")) else min(int(qty), bag[ore])
        if q <= 0:
            return {"err": "Пусто"}
        earned = q * ORES[ore]["price"]
        with _db_lock, db() as c:
            c.execute("UPDATE bag SET qty=qty-? WHERE user_id=? AND ore=?", (q, u["user_id"], ore))
        u["money"] += earned
        save_user(u)
        quests_add(u["user_id"], "sell", earned)
        return {"ok": True, "earned": earned, "ore": ore, "qty": q}
    total = sum(bag[k] * ORES[k]["price"] for k in bag)
    if total <= 0:
        return {"err": "Рюкзак пуст"}
    with _db_lock, db() as c:
        c.execute("DELETE FROM bag WHERE user_id=?", (u["user_id"],))
    u["money"] += total
    save_user(u)
    quests_add(u["user_id"], "sell", total)
    return {"ok": True, "earned": total}

def refill_energy(u):
    if u["energy"] >= ENERGY_MAX:
        return {"err": "Энергия уже полная"}
    if u["money"] < ENERGY_REFILL_PRICE:
        return {"err": "Не хватает монет"}
    u["money"] -= ENERGY_REFILL_PRICE
    u["energy"] = ENERGY_MAX
    u["energy_ts"] = int(time.time())
    save_user(u)
    return {"ok": True}

def set_location(u, key):
    loc = LOCATION_BY_KEY.get(key)
    if not loc:
        return {"err": "Нет такой шахты"}
    if level_of(u["xp"]) < loc["level"]:
        return {"err": "Нужен %d уровень" % loc["level"]}
    u["location"] = key
    save_user(u)
    return {"ok": True}

def claim_quest(u, key):
    q = QUEST_BY_KEY.get(key)
    if not q:
        return {"err": "Нет такого задания"}
    with _db_lock, db() as c:
        row = c.execute("SELECT * FROM quests WHERE user_id=? AND qkey=?", (u["user_id"], key)).fetchone()
        p = row["p"] if row else 0
        claimed = row["claimed"] if row else 0
        if claimed:
            return {"err": "Уже получено"}
        if p < q["target"]:
            return {"err": "Прогресс %d/%d" % (p, q["target"])}
        c.execute("UPDATE quests SET claimed=1, p=0 WHERE user_id=? AND qkey=?", (u["user_id"], key))
        c.execute("UPDATE users SET money=money+?, xp=xp+? WHERE user_id=?", (q["money"], q["xp"], u["user_id"]))
    return {"ok": True, "text": "+%d монет, +%d опыта" % (q["money"], q["xp"])}

def apply_promo(u, code):
    code = (code or "").strip().upper()
    with _db_lock, db() as c:
        row = c.execute("SELECT * FROM promos WHERE code=?", (code,)).fetchone()
        if not row or row["uses"] <= 0:
            return {"err": "Промокод не найден или закончился"}
        c.execute("UPDATE promos SET uses=uses-1 WHERE code=?", (code,))
        if row["kind"] == "money":
            c.execute("UPDATE users SET money=money+? WHERE user_id=?", (row["value"], u["user_id"]))
            return {"ok": True, "text": "🪙 +%d монет" % row["value"]}
        if row["kind"] == "xp":
            c.execute("UPDATE users SET xp=xp+? WHERE user_id=?", (row["value"], u["user_id"]))
            return {"ok": True, "text": "✨ +%d опыта" % row["value"]}
        if row["kind"] == "ore":
            ore, q = rand_ore_pack()
            bag_add(u["user_id"], ore, q)
            return {"ok": True, "text": "%s ×%d" % (ORES[ore]["name"], q)}
    return {"err": "Неизвестный тип промокода"}

def transfer_money(from_id, to_id, amount):
    amount = int(amount)
    if amount <= 0:
        return {"err": "Сумма должна быть больше 0"}
    with _db_lock, db() as c:
        r1 = c.execute("SELECT money FROM users WHERE user_id=?", (from_id,)).fetchone()
        r2 = c.execute("SELECT user_id FROM users WHERE user_id=?", (to_id,)).fetchone()
        if not r1 or not r2:
            return {"err": "Игрок не найден (нужно, чтобы он запускал бота)"}
        if r1["money"] < amount:
            return {"err": "Не хватает монет"}
        fee = int(amount * TRANSFER_FEE)
        c.execute("UPDATE users SET money=money-? WHERE user_id=?", (amount, from_id))
        c.execute("UPDATE users SET money=money+? WHERE user_id=?", (amount - fee, to_id))
    return {"ok": True, "fee": fee, "amount": amount - fee}

def top_users():
    with _db_lock, db() as c:
        rows = [dict(r) for r in c.execute("SELECT user_id, name, money, xp, avatar_mode, avatar_emoji FROM users ORDER BY money DESC LIMIT 20")]
        rows2 = [dict(r) for r in c.execute("SELECT user_id, name, money, xp, avatar_mode, avatar_emoji FROM users ORDER BY xp DESC LIMIT 20")]
    def fmt(rows):
        return [{"user_id": r["user_id"], "name": r["name"] or str(r["user_id"]), "money": r["money"],
                 "xp": r["xp"], "level": level_of(r["xp"]),
                 "avatar": ("/avatars/%d.png" % r["user_id"]) if r["avatar_mode"] == "photo" else None,
                 "emoji": r["avatar_emoji"] if r["avatar_mode"] == "emoji" else None} for r in rows]
    return {"money": fmt(rows), "xp": fmt(rows2)}

def fmt_left(sec):
    sec = max(0, int(sec))
    h, m = sec // 3600, (sec % 3600) // 60
    if h:
        return "%d ч %d мин" % (h, m)
    if m:
        return "%d мин" % m
    return "%d сек" % sec

def user_payload(u):
    lvl, rest, need = level_progress(u["xp"])
    bag = bag_get(u["user_id"])
    now = int(time.time())
    ch = get_char(u["char_key"]) if u["char_key"] else None
    my_chars = []
    with _db_lock, db() as c:
        my_chars = [r["char_key"] for r in c.execute("SELECT char_key FROM chars WHERE user_id=?", (u["user_id"],))]
    avatar = None
    if u["avatar_mode"] == "photo":
        avatar = "/avatars/%d.png" % u["user_id"]
    elif u["avatar_mode"] == "emoji":
        avatar = u["avatar_emoji"]
    return {
        "user_id": u["user_id"], "name": u["name"], "money": u["money"], "xp": u["xp"],
        "level": lvl, "lvl_rest": rest, "lvl_need": need,
        "energy": u["energy"], "energy_max": ENERGY_MAX,
        "energy_next_sec": ENERGY_REGEN_MIN * 60 - (now - u["energy_ts"]) % (ENERGY_REGEN_MIN * 60),
        "pickaxe": u["pickaxe"], "location": u["location"], "char": ch,
        "bag": bag, "chars": my_chars, "quests": quests_state(u["user_id"]),
        "bonus_in": max(0, BONUS_CD_H * 3600 - (now - (u["bonus_ts"] or 0))),
        "case_in": max(0, CASE_CD_H * 3600 - (now - (u["case_ts"] or 0))),
        "auto_level": u["auto_level"], "auto_ts": u["auto_ts"],
        "discount_pct": u["discount_pct"] if (u["discount_ts"] or 0) > now else 0,
        "avatar_mode": u["avatar_mode"], "avatar": avatar,
        "avatar_emoji": u["avatar_emoji"],
        "sectors": ROULETTE_SECTORS, "min_bet": ROULETTE_MIN_BET,
        "ores": ORES, "pickaxes": PICKAXES, "locations": LOCATIONS,
        "characters": CHARACTERS, "rar_colors": RARITY_COLORS,
        "auto_interval_h": AUTO_INTERVAL_H, "auto_max": AUTO_MAX_LEVEL,
        "refill_price": ENERGY_REFILL_PRICE,
        "top": top_users(),
        "now": now,
    }

# ================= ПОДПИСЬ initData =================
def verify_init(init):
    if not init:
        return None
    try:
        pairs = dict(parse_qsl(init, keep_blank_values=True))
    except Exception:
        return None
    h = pairs.pop("hash", None)
    if not h:
        return None
    data_check = "\n".join("%s=%s" % (k, pairs[k]) for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if calc != h:
        return None
    try:
        if int(time.time()) - int(pairs.get("auth_date", 0)) > 7 * 86400:
            return None
        user = json.loads(pairs.get("user", "{}"))
    except Exception:
        return None
    if not user.get("id"):
        return None
    return user

# ================= HTTP =================
def safe_file(base, name, exts=("",)):
    name = os.path.basename(name or "")
    for ext in exts:
        p = os.path.join(base, name + ext)
        if os.path.isfile(p):
            return p
    return None

CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".gif": "image/gif", ".webp": "image/webp"}

def serve_file(path):
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        data = f.read()
    return aio_web.Response(body=data, content_type=CONTENT_TYPES.get(ext, "application/octet-stream"))

async def h_app(request):
    return aio_web.Response(text=PAGE_HTML, content_type="text/html", charset="utf-8")

async def h_img(request):
    name = request.match_info["name"]
    p = safe_file(IMG_DIR, name, ("", ".gif", ".png", ".jpg", ".jpeg", ".webp"))
    if not p:
        return aio_web.Response(status=404, text="not found")
    return serve_file(p)

async def h_avatar_file(request):
    name = request.match_info["name"]
    p = safe_file(AVATAR_DIR, name, ("", ".png", ".jpg", ".jpeg", ".webp"))
    if not p:
        return aio_web.Response(status=404, text="not found")
    return serve_file(p)

async def h_avatar_upload(request):
    try:
        body = json.loads(await request.text())
    except Exception:
        return aio_web.json_response({"err": "bad json"})
    user = verify_init(body.get("init"))
    if not user:
        return aio_web.json_response({"err": "auth failed"})
    data_url = body.get("data", "")
    m = re.match(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$", data_url or "", re.S)
    if not m:
        return aio_web.json_response({"err": "Нужна картинка PNG/JPG/WebP"})
    raw = base64.b64decode(m.group(2))
    if len(raw) > 3 * 1024 * 1024:
        return aio_web.json_response({"err": "Файл больше 3 МБ"})
    ext = "png" if m.group(1) == "png" else ("jpg" if m.group(1) in ("jpeg", "jpg") else "webp")
    fname = "%s.%s" % (user["id"], ext)
    # убрать старые файлы этого пользователя
    for e in ("png", "jpg", "webp"):
        old = os.path.join(AVATAR_DIR, "%s.%s" % (user["id"], e))
        if os.path.isfile(old) and old != os.path.join(AVATAR_DIR, fname):
            os.remove(old)
    with open(os.path.join(AVATAR_DIR, fname), "wb") as f:
        f.write(raw)
    u = get_user(user["id"], user.get("full_name") or user.get("username") or "")
    u["avatar_mode"] = "photo"
    save_user(u)
    return aio_web.json_response({"ok": True, "avatar": "/avatars/%s" % fname})

API_ACTIONS = {}

def api_action(name):
    def deco(fn):
        API_ACTIONS[name] = fn
        return fn
    return deco

@api_action("mine")
def act_mine(u, p): return do_mine(u)

@api_action("spin")
def act_spin(u, p): return spin_roulette(u, p.get("bet", 0))

@api_action("bonus")
def act_bonus(u, p): return claim_bonus(u)

@api_action("case")
def act_case(u, p): return open_case(u)

@api_action("buy_pick")
def act_buy_pick(u, p): return buy_pickaxe(u, p.get("key", ""))

@api_action("buy_auto")
def act_buy_auto(u, p): return buy_auto(u)

@api_action("collect_auto")
def act_collect(u, p): return collect_auto(u)

@api_action("sell")
def act_sell(u, p):
    return sell_ores(u, p.get("ore"), p.get("qty"))

@api_action("set_loc")
def act_set_loc(u, p): return set_location(u, p.get("key", ""))

@api_action("refill")
def act_refill(u, p): return refill_energy(u)

@api_action("set_char")
def act_set_char(u, p):
    key = p.get("key", "")
    if key and not have_char(u["user_id"], key):
        return {"err": "Персонаж не найден в коллекции"}
    u["char_key"] = key
    save_user(u)
    return {"ok": True}

@api_action("set_emoji")
def act_set_emoji(u, p):
    e = p.get("emoji", "⛏️")
    if e not in EMOJI_AVATARS:
        return {"err": "Нет такого эмодзи"}
    u["avatar_mode"], u["avatar_emoji"] = "emoji", e
    save_user(u)
    return {"ok": True}

@api_action("avatar_tg")
def act_avatar_tg(u, p):
    u["avatar_mode"] = "tg"
    save_user(u)
    return {"ok": True}

@api_action("claim_quest")
def act_claim_quest(u, p): return claim_quest(u, p.get("key", ""))

@api_action("promo")
def act_promo(u, p): return apply_promo(u, p.get("code", ""))

@api_action("state")
def act_state(u, p): return {"ok": True}

async def api_handler(request):
    action = request.match_info["action"]
    try:
        body = json.loads(await request.text())
    except Exception:
        return aio_web.json_response({"err": "bad json"})
    user = verify_init(body.get("init", ""))
    if not user:
        return aio_web.json_response({"err": "auth failed"}, status=401)
    uid = user["id"]
    name = user.get("full_name") or ((user.get("first_name") or "") + " " + (user.get("last_name") or "")).strip() or user.get("username") or str(uid)
    u = get_user(uid, name)
    fn = API_ACTIONS.get(action)
    if not fn:
        return aio_web.json_response({"err": "unknown action"})
    try:
        res = fn(u, body)
    except Exception as e:
        return aio_web.json_response({"err": "Ошибка: %s" % e})
    if res.get("err"):
        return aio_web.json_response(res)
    return aio_web.json_response({**res, "state": user_payload(u)})

# ================= MINI APP: HTML/CSS =================
HTML_PART1 = r"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>⛏ Шахтёр</title>
<style>
:root{--bg:#0e1116;--card:#171c24;--card2:#1e2530;--line:#2a3341;--txt:#e8ecf1;--dim:#8b97a5;
--gold:#ffc400;--green:#2ecc71;--red:#ff5c5c;--blue:#4aa3ff;--purple:#b46bff}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--txt);font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
padding-bottom:76px;min-height:100vh}
header{position:sticky;top:0;z-index:10;background:rgba(14,17,22,.92);backdrop-filter:blur(8px);
padding:10px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}
.avatar{width:44px;height:44px;border-radius:50%;background:var(--card2);display:flex;align-items:center;
justify-content:center;font-size:24px;overflow:hidden;flex-shrink:0;border:2px solid var(--line)}
.avatar img{width:100%;height:100%;object-fit:cover}
.hinfo{flex:1;min-width:0}
.hname{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hlvl{font-size:11px;color:var(--dim)}
.lvlbar{height:4px;background:var(--line);border-radius:2px;margin-top:4px}
.lvlbar i{display:block;height:100%;background:var(--gold);border-radius:2px}
.hmoney{text-align:right}
.hmoney b{color:var(--gold);font-size:16px}
.henergy{font-size:11px;color:var(--dim)}
main{padding:12px}
.tab{display:none}.tab.on{display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:10px}
.card h3{font-size:14px;margin-bottom:8px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px}
.btn{display:block;width:100%;border:0;border-radius:12px;padding:13px;font-size:16px;font-weight:700;
color:#fff;cursor:pointer;margin-top:8px;background:var(--card2)}
.btn:active{opacity:.75}
.btn.gold{background:linear-gradient(135deg,#f5a623,#c78100);color:#1a1200}
.btn.green{background:linear-gradient(135deg,#27ae60,#1d8348)}
.btn.red{background:linear-gradient(135deg,#e74c3c,#a93226)}
.btn.blue{background:linear-gradient(135deg,#2980b9,#1f618d)}
.btn[disabled]{opacity:.4}
.row{display:flex;gap:8px;align-items:center}
.row .btn{margin-top:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.bigbtn{background:linear-gradient(135deg,#f5a623,#c78100);color:#1a1200;border:0;border-radius:16px;
width:100%;padding:22px;font-size:20px;font-weight:800;cursor:pointer}
.bigbtn:active{opacity:.8}
.bigbtn[disabled]{opacity:.4}
.energywrap{margin:8px 0}
.ebar{height:10px;background:var(--line);border-radius:5px;overflow:hidden}
.ebar i{display:block;height:100%;background:linear-gradient(90deg,#2ecc71,#27ae60)}
.etext{font-size:12px;color:var(--dim);margin-top:4px;display:flex;justify-content:space-between}
.sect{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
.sect span{background:var(--card2);border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:12px}
.sect span.j{border-color:var(--gold);color:var(--gold)}
.betrow{display:flex;gap:6px;margin-top:8px}
.betrow button{flex:1;background:var(--card2);border:1px solid var(--line);color:var(--txt);border-radius:10px;
padding:10px 0;font-size:13px;cursor:pointer}
.betrow button.on{border-color:var(--gold);color:var(--gold)}
.loc{display:flex;gap:12px;align-items:center;background:var(--card);border:1px solid var(--line);
border-radius:14px;padding:10px;margin-bottom:10px;cursor:pointer}
.loc.on{border-color:var(--gold)}
.loc img{width:72px;height:72px;border-radius:10px;object-fit:cover;background:var(--card2)}
.loc .ln{font-weight:700;font-size:14px}
.loc .ld{font-size:12px;color:var(--dim)}
.loc.locked{opacity:.45}
.item{display:flex;gap:10px;align-items:center;background:var(--card);border:1px solid var(--line);
border-radius:14px;padding:12px;margin-bottom:10px}
.item .ic{font-size:28px;width:44px;text-align:center;flex-shrink:0}
.item .info{flex:1;min-width:0}
.item .nm{font-weight:700;font-size:14px}
.item .ds{font-size:12px;color:var(--dim)}
.pbar{height:6px;background:var(--line);border-radius:3px;margin-top:6px;overflow:hidden}
.pbar i{display:block;height:100%;background:var(--blue);border-radius:3px}
.tag{font-size:10px;padding:2px 8px;border-radius:8px;color:#111;font-weight:700}
.mini{font-size:12px;padding:9px 14px;border-radius:10px;border:0;font-weight:700;cursor:pointer;background:var(--card2);color:var(--txt)}
.mini.gold{background:var(--gold);color:#1a1200}
.mini.green{background:var(--green);color:#06240f}
.mini:disabled{opacity:.4}
nav{position:fixed;bottom:0;left:0;right:0;background:rgba(23,28,36,.97);border-top:1px solid var(--line);
display:flex;z-index:20;padding:6px 2px calc(6px + env(safe-area-inset-bottom))}
nav button{flex:1;background:0;border:0;color:var(--dim);font-size:10px;display:flex;flex-direction:column;
align-items:center;gap:2px;cursor:pointer;padding:4px 0}
nav button i{font-size:20px;font-style:normal}
nav button.on{color:var(--gold)}
.toprow{display:flex;align-items:center;gap:10px;padding:10px;border-bottom:1px solid var(--line)}
.toprow .avatar{width:38px;height:38px;font-size:19px}
.toprow .pos{width:26px;color:var(--dim);font-weight:700}
.toprow.first .pos{color:var(--gold)}
.chars{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.charcard{background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:10px 6px;
text-align:center;font-size:26px;cursor:pointer;position:relative}
.charcard.on{border-color:var(--gold)}
.charcard.no{opacity:.25}
.charcard .cn{font-size:10px;margin-top:4px;color:var(--txt)}
.charcard .cb{font-size:9px;color:var(--dim)}
.toast{position:fixed;left:50%;bottom:90px;transform:translateX(-50%);background:var(--card2);
border:1px solid var(--line);color:var(--txt);padding:12px 18px;border-radius:12px;z-index:50;
max-width:90vw;text-align:center;display:none;font-size:14px}
.notice{font-size:12px;color:var(--dim);margin-top:6px}
.statrow{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line);font-size:14px}
.statrow b{color:var(--gold)}
.headbtn{background:var(--card2);border:1px solid var(--line);color:var(--txt);border-radius:10px;
padding:8px 12px;font-size:12px;cursor:pointer}
input[type=text]{width:100%;background:var(--card2);border:1px solid var(--line);color:var(--txt);
border-radius:10px;padding:11px;font-size:14px;outline:0}
</style></head><body>
<header>
 <div class="avatar" id="hava"></div>
 <div class="hinfo"><div class="hname" id="hname">...</div><div class="hlvl" id="hlvl"></div>
 <div class="lvlbar"><i id="hlvlbar" style="width:0%"></i></div></div>
 <div class="hmoney"><b id="hmoney">0</b> 🪙<div class="henergy" id="henergy"></div></div>
</header>
<main>
 <section class="tab on" id="tab-mine">
  <div class="energywrap"><div class="ebar"><i id="ebar" style="width:0%"></i></div>
  <div class="etext"><span id="etext"></span><span id="etimer"></span></div></div>
  <button class="bigbtn" id="digbtn">⛏ КОПАТЬ</button>
  <div class="card"><h3>🎰 Рулетка</h3>
   <div class="sect" id="sectors"></div>
   <div class="betrow" id="bets"></div>
   <button class="btn gold" id="spinbtn">КРУТИТЬ</button>
   <div class="notice" id="spinlvlnote"></div></div>
  <div class="grid2">
   <div class="card"><h3>🎁 Бонус · 12ч</h3><div id="bonusinfo" class="ds"></div>
   <button class="btn green" id="bonusbtn">Забрать</button></div>
   <div class="card"><h3>📦 Кейс · 24ч</h3><div id="caseinfo" class="ds"></div>
   <button class="btn blue" id="casebtn">Открыть</button></div>
  </div>
 </section>
 <section class="tab" id="tab-bag"><div id="baglist"></div></section>
 <section class="tab" id="tab-mines"><div id="loclist"></div></section>
 <section class="tab" id="tab-shop"><div id="shoplist"></div></section>
 <section class="tab" id="tab-auto"><div id="autobox"></div></section>
 <section class="tab" id="tab-quests"><div id="questlist"></div>
  <div class="card"><h3>🎟 Промокод</h3><input type="text" id="promocode" placeholder="Введи код">
  <button class="btn" id="promobtn">Активировать</button></div></section>
 <section class="tab" id="tab-top"><div class="row" style="margin-bottom:10px">
  <button class="mini gold" id="topmoney">🪙 Богатейшие</button>
  <button class="mini" id="topxp">✨ Опытные</button></div>
  <div id="toplist"></div></section>
 <section class="tab" id="tab-profile"><div id="profilebox"></div></section>
</main>
<div class="toast" id="toast"></div>
<nav id="nav"></nav>
"""

# ================= MINI APP: JS =================
HTML_PART2 = r"""
<script>
const initData = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp.initData : '';
const S = {tab:'mine', bet:100, topMode:'money', st:null};
const fmt = n => (Math.floor(n)).toLocaleString('ru-RU');
function haptic(){ try{Telegram.WebApp.HapticFeedback.impactOccurred('light')}catch(e){} }
function toast(msg, ms=2600){ const t=document.getElementById('toast'); t.textContent=msg; t.style.display='block';
 clearTimeout(t._tm); t._tm=setTimeout(()=>t.style.display='none', ms); }
async function api(action, params={}){
 try{
  const r = await fetch('/api/'+action, {method:'POST', headers:{'Content-Type':'application/json'},
   body: JSON.stringify(Object.assign({init: initData}, params))});
  const j = await r.json();
  if(j.state) S.st = j.state;
  return j;
 }catch(e){ return {err:'Нет связи с сервером'}; }
}
function renderAll(){
 const s = S.st; if(!s) return;
 document.getElementById('hname').textContent = s.name || 'Шахтёр';
 document.getElementById('hlvl').textContent = 'Уровень ' + s.level + ' · опыт ' + fmt(s.lvl_rest) + '/' + fmt(s.lvl_need);
 document.getElementById('hlvlbar').style.width = Math.min(100, 100*s.lvl_rest/s.lvl_need) + '%';
 document.getElementById('hmoney').textContent = fmt(s.money);
 document.getElementById('henergy').textContent = '⚡ ' + s.energy + '/' + s.energy_max;
 const av = document.getElementById('hava');
 if(s.avatar_mode==='photo' && s.avatar){ av.innerHTML = '<img src="'+s.avatar+'?t='+s.now+'">'; }
 else { av.textContent = s.avatar_mode==='emoji' ? s.avatar_emoji : '👤'; }
 renderMine(); renderBag(); renderMines(); renderShop(); renderAuto(); renderQuests(); renderTop(); renderProfile();
}
function setTab(id){ S.tab=id; haptic();
 document.querySelectorAll('main .tab').forEach(e=>e.classList.remove('on'));
 document.getElementById('tab-'+id).classList.add('on');
 document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on', b.dataset.tab===id));
 window.scrollTo(0,0);
}
function renderMine(){
 const s = S.st;
 const ebar = document.getElementById('ebar');
 ebar.style.width = (100*s.energy/s.energy_max)+'%';
 document.getElementById('etext').textContent = '⚡ Энергия: '+s.energy+'/'+s.energy_max;
 document.getElementById('etimer').textContent = s.energy>=s.energy_max ? 'полная' : '+1 через '+Math.ceil(s.energy_next_sec/60)+' мин';
 const dig = document.getElementById('digbtn');
 dig.disabled = s.energy<=0;
 dig.textContent = s.energy>0 ? '⛏ КОПАТЬ' : '⚡ НЕТ ЭНЕРГИИ';
 const sec = document.getElementById('sectors'); sec.innerHTML='';
 s.sectors.forEach(([m,ch])=>{ const sp=document.createElement('span');
  sp.textContent='×'+m+' ('+ch+'%)'; if(m>=3) sp.className='j'; sec.appendChild(sp); });
 if(!document.getElementById('bets').children.length){
  [100,500,1000,5000].forEach(b=>{ const bt=document.createElement('button'); bt.textContent=fmt(b);
   bt.onclick=()=>{S.bet=b; haptic(); document.querySelectorAll('#bets button').forEach(x=>x.classList.remove('on')); bt.classList.add('on');};
   if(b===S.bet) bt.classList.add('on'); document.getElementById('bets').appendChild(bt); });
  const all=document.createElement('button'); all.textContent='ВСЁ';
  all.onclick=()=>{S.bet='all'; document.querySelectorAll('#bets button').forEach(x=>x.classList.remove('on')); all.classList.add('on');};
  document.getElementById('bets').appendChild(all);
 }
 document.getElementById('spinbtn').disabled = s.level < 20;
 document.getElementById('spinlvlnote').textContent = s.level<20 ? 'Рулетка откроется на '+20+' уровне' : 'Ставка: '+(S.bet==='all'?'всё ('+fmt(s.money)+')':fmt(S.bet))+' монет';
 const bIn = s.bonus_in>0, cIn = s.case_in>0;
 const bb = document.getElementById('bonusbtn'); bb.disabled=bIn;
 document.getElementById('bonusinfo').textContent = bIn ? 'через '+fmtLeft(s.bonus_in) : 'Монеты, опыт, руда, скидка или персонаж (4%)';
 const cb = document.getElementById('casebtn'); cb.disabled=cIn;
 document.getElementById('caseinfo').textContent = cIn ? 'через '+fmtLeft(s.case_in) : 'Монеты 100–100к, руда, скидка или персонаж (8%)';
}
function fmtLeft(sec){ sec=Math.ceil(sec/60); if(sec<60) return sec+' мин';
 const h=Math.floor(sec/60), m=sec%60; return h+' ч '+m+' мин'; }
async function doDig(){
 const d = document.getElementById('digbtn'); d.disabled=true;
 const j = await api('mine'); haptic();
 if(j.err) toast(j.err);
 else { let t = j.ore+' ×'+j.qty+'  (+'+j.xp+' опыта)';
  if(j.char) t = '🎉 ПЕРСОНАЖ: '+j.char.name+'!  |  '+t;
  toast(t, 3200); }
 renderAll(); d.disabled = S.st.energy<=0;
}
async function doSpin(){
 const s=S.st; const bet = S.bet==='all' ? s.money : S.bet;
 const j = await api('spin', {bet:bet}); haptic();
 if(j.err) toast(j.err);
 else toast(j.mult===0 ? '💀 Мимо! Ставка сгорела' : '✅ ×'+j.mult+' → выпало '+fmt(j.payout), 3000);
 renderAll();
}
function renderBag(){
 const s=S.st, el=document.getElementById('baglist'); el.innerHTML='';
 const keys = Object.keys(s.bag).filter(k=>s.bag[k]>0);
 if(!keys.length){ el.innerHTML='<div class="card">Рюкзак пуст. Иди копать! ⛏</div>'; return; }
 let total=0;
 keys.forEach(k=>{ const o=s.ores[k]; if(!o) return; total+=s.bag[k]*o.price;
  const d=document.createElement('div'); d.className='item';
  d.innerHTML='<div class="ic">'+o.name.split(' ')[0]+'</div><div class="info"><div class="nm">'+
   o.name.replace(/^[^ ]+ /,'')+' — '+s.bag[k]+' шт</div><div class="ds">'+o.price+' монет за шт</div></div>';
  const b1=document.createElement('button'); b1.className='mini'; b1.textContent='×1';
  b1.onclick=()=>actSell(k,1);
  const b10=document.createElement('button'); b10.className='mini'; b10.textContent='×10';
  b10.onclick=()=>actSell(k,10);
  const ba=document.createElement('button'); ba.className='mini gold'; ba.textContent='Всё';
  ba.onclick=()=>actSell(k,'all');
  d.appendChild(b1); d.appendChild(b10); d.appendChild(ba); el.appendChild(d); });
 const sum=document.createElement('div'); sum.className='card';
 sum.innerHTML='<div class="row"><div class="info"><div class="nm">Всего на '+fmt(total)+' 🪙</div></div></div>';
 const ball=document.createElement('button'); ball.className='btn green'; ball.textContent='Продать ВСЁ';
 ball.onclick=()=>actSell(null,'all'); sum.appendChild(ball); el.appendChild(sum);
}
async function actSell(ore, qty){
 const j = await api('sell', {ore:ore, qty:qty}); haptic();
 toast(j.err || '💰 Продано на '+fmt(j.earned)+' монет'); renderAll();
}
function renderMines(){
 const s=S.st, el=document.getElementById('loclist'); el.innerHTML='';
 s.locations.forEach(l=>{
  const d=document.createElement('div'); const locked = s.level < l.level;
  d.className='loc'+(s.location===l.key?' on':'')+(locked?' locked':'');
  const img = document.createElement('img'); img.src='/img/'+l.key; img.onerror=()=>img.style.display='none';
  d.appendChild(img);
  const info=document.createElement('div'); info.className='info';
  info.innerHTML='<div class="ln">'+l.name+'</div><div class="ld">'+l.desc+(locked?' · 🔒 уровень '+l.level:'')+'</div>';
  d.appendChild(info);
  d.onclick=async()=>{ if(locked){ toast('🔒 Нужен '+l.level+' уровень'); return; }
   const j=await api('set_loc',{key:l.key}); haptic(); toast(j.err||'Выбрано: '+l.name); renderAll(); };
  el.appendChild(d);
 });
}
function renderShop(){
 const s=S.st, el=document.getElementById('shoplist'); el.innerHTML='';
 const order = s.pickaxes.map(p=>p.key); const cur = order.indexOf(s.pickaxe);
 s.refill = s.refill_price;
 const en=document.createElement('div'); en.className='item';
 en.innerHTML='<div class="ic">⚡</div><div class="info"><div class="nm">Восстановить энергию</div><div class="ds">'+s.energy+'/'+s.energy_max+' зарядов · '+fmt(s.refill_price)+' монет</div></div>';
 const be=document.createElement('button'); be.className='mini gold'; be.textContent='Купить';
 be.onclick=async()=>{ const j=await api('refill'); toast(j.err||'⚡ Энергия полная'); renderAll(); };
 en.appendChild(be); el.appendChild(en);
 s.pickaxes.forEach((p,i)=>{
  const owned = i<=cur;
  const d=document.createElement('div'); d.className='item';
  d.innerHTML='<div class="ic">⛏️</div><div class="info"><div class="nm">'+p.name+'</div><div class="ds">Сила '+p.power+' · с '+p.level+' уровня</div></div>';
  if(owned){ const t=document.createElement('span'); t.className='tag';
   t.style.background = i===cur?'#2ecc71':'#3a4351'; t.style.color = i===cur?'#06240f':'#cfd8e0';
   t.textContent = i===cur?'УСТАНОВЛЕНА':'Куплена'; d.appendChild(t); }
  else{
   const disc = s.discount_pct>0 ? Math.floor(p.price*(100-s.discount_pct)/100) : p.price;
   const b=document.createElement('button'); b.className='mini gold';
   b.textContent = s.discount_pct>0 ? fmt(disc)+' (-'+s.discount_pct+'%)' : fmt(p.price);
   b.onclick=async()=>{ const j=await api('buy_pick',{key:p.key}); toast(j.err||'✅ Куплено: '+j.name); renderAll(); };
   d.appendChild(b);
  }
  el.appendChild(d);
 });
 const rf=document.createElement('div'); rf.className='card';
 rf.innerHTML='<div class="notice">🏷 Скидка '+(s.discount_pct?s.discount_pct+'% действует на первую покупку':'нет активной')+
  '. Возврат последней покупки — 15 минут, командой /refund в чате.</div>';
 el.appendChild(rf);
}
function renderAuto(){
 const s=S.st, el=document.getElementById('autobox'); el.innerHTML='';
 const d=document.createElement('div'); d.className='card';
 if(s.auto_level===0){
  d.innerHTML='<h3>🤖 Автосбор</h3><div class="ds">Шахта копает сама каждые '+s.auto_interval_h+' ч, даже когда ты офлайн. Цена: 5000 монет.</div>';
  const b=document.createElement('button'); b.className='btn gold'; b.textContent='Купить за 5000';
  b.onclick=async()=>{ const j=await api('buy_auto'); toast(j.err||'🤖 Автосбор куплен!'); renderAll(); };
  d.appendChild(b);
 } else {
  const waited = s.now - s.auto_ts;
  const cycles = Math.floor(waited/(s.auto_interval_h*3600));
  d.innerHTML='<h3>🤖 Автосбор · уровень '+s.auto_level+'/'+s.auto_max+'</h3><div class="ds">Циклов накоплено: '+cycles+
   ' · следующий через '+fmtLeft(Math.max(0,(s.auto_interval_h*3600)-waited))+'</div>';
  const b=document.createElement('button'); b.className='btn green'; b.textContent='Забрать руду';
  b.onclick=async()=>{ const j=await api('collect_auto');
   if(j.err) toast(j.err); else { const parts=Object.entries(j.got).map(([k,v])=>s.ores[k].name+' ×'+v);
    toast('🤖 Забрал: '+parts.join(', '), 3500); } renderAll(); };
  d.appendChild(b);
  if(s.auto_level < s.auto_max){
   const price=5000*Math.pow(2,s.auto_level);
   const b2=document.createElement('button'); b2.className='btn gold'; b2.textContent='Улучшить за '+fmt(price);
   b2.onclick=async()=>{ const j=await api('buy_auto'); toast(j.err||'⬆️ Уровень '+j.level); renderAll(); };
   d.appendChild(b2);
  }
 }
 el.appendChild(d);
}
function renderQuests(){
 const s=S.st, el=document.getElementById('questlist'); el.innerHTML='';
 s.quests.forEach(q=>{
  const d=document.createElement('div'); d.className='item';
  d.innerHTML='<div class="info"><div class="nm">'+q.name+'</div><div class="ds">'+Math.min(q.p,q.target)+'/'+q.target+
   ' · награда: '+fmt(q.money)+' монет, '+q.xp+' опыта</div><div class="pbar"><i style="width:'+Math.min(100,100*q.p/q.target)+'%"></i></div></div>';
  if(q.claimed){ const t=document.createElement('span'); t.className='tag'; t.style.background='#2ecc71';
   t.style.color='#06240f'; t.textContent='ПОЛУЧЕНО'; d.appendChild(t); }
  else if(q.p>=q.target){ const b=document.createElement('button'); b.className='mini gold'; b.textContent='Забрать';
   b.onclick=async()=>{ const j=await api('claim_quest',{key:q.key}); toast(j.err||'✅ '+j.text); renderAll(); };
   d.appendChild(b); }
  el.appendChild(d);
 });
}
function renderTop(){
 const s=S.st, list = S.topMode==='money' ? s.top.money : s.top.xp;
 const el=document.getElementById('toplist'); el.innerHTML='';
 document.getElementById('topmoney').className = S.topMode==='money'?'mini gold':'mini';
 document.getElementById('topxp').className = S.topMode==='xp'?'mini gold':'mini';
 list.forEach((r,i)=>{
  const d=document.createElement('div'); d.className='toprow'+(i===0?' first':'');
  const av=document.createElement('div'); av.className='avatar';
  if(r.avatar){ av.innerHTML='<img src="'+r.avatar+'">'; } else { av.textContent=r.emoji||'👤'; }
  d.appendChild(av);
  const pos=document.createElement('div'); pos.className='pos'; pos.textContent=(i+1); d.appendChild(pos);
  const info=document.createElement('div'); info.className='info';
  info.innerHTML='<div class="nm">'+r.name+'</div><div class="ds">Уровень '+r.level+'</div>';
  d.appendChild(info);
  const val=document.createElement('div'); val.className='nm';
  val.textContent = S.topMode==='money' ? fmt(r.money)+' 🪙' : fmt(r.xp)+' ✨';
  d.appendChild(val); el.appendChild(d);
 });
}
function renderProfile(){
 const s=S.st, el=document.getElementById('profilebox'); el.innerHTML='';
 const d=document.createElement('div'); d.className='card';
 const av=document.createElement('div'); av.className='avatar'; av.style.cssText='width:72px;height:72px;font-size:38px;margin:0 auto 8px';
 if(s.avatar_mode==='photo' && s.avatar){ av.innerHTML='<img src="'+s.avatar+'?t='+s.now+'">'; }
 else { av.textContent = s.avatar_mode==='emoji'?s.avatar_emoji:'👤'; }
 d.appendChild(av);
 const info=document.createElement('div');
 info.innerHTML='<div style="text-align:center;font-weight:700">'+(s.name||'')+'</div>'+
  '<div class="statrow"><span>🪙 Монеты</span><b>'+fmt(s.money)+'</b></div>'+
  '<div class="statrow"><span>✨ Опыт</span><b>'+fmt(s.xp)+'</b></div>'+
  '<div class="statrow"><span>📈 Уровень</span><b>'+s.level+'</b></div>'+
  '<div class="statrow"><span>⛏ Кирка</span><b>'+(s.pickaxes.find(p=>p.key===s.pickaxe)||{}).name+'</b></div>'+
  '<div class="statrow"><span>🎞 Персонажей</span><b>'+s.chars.length+'</b></div>';
 d.appendChild(info);
 const btns=document.createElement('div'); btns.className='grid2'; btns.style.marginTop='10px';
 const up=document.createElement('button'); up.className='btn'; up.textContent='📷 Загрузить фото';
 const inp=document.createElement('input'); inp.type='file'; inp.accept='image/*'; inp.style.display='none';
 inp.onchange=()=>{ const f=inp.files[0]; if(!f) return;
  if(f.size>3*1024*1024){ toast('Файл больше 3 МБ'); return; }
  const rd=new FileReader(); rd.onload=async()=>{ const j=await fetch('/api/avatar',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({init:initData,data:rd.result})});
   const jj=await j.json(); toast(jj.err||'✅ Аватар обновлён'); renderAll(); }; rd.readAsDataURL(f); };
 up.onclick=()=>inp.click(); btns.appendChild(up); btns.appendChild(inp);
 const tg=document.createElement('button'); tg.className='btn'; tg.textContent='Telegram-фото';
 tg.onclick=async()=>{ await api('avatar_tg'); toast('Фото из Telegram'); renderAll(); };
 btns.appendChild(tg);
 const em=document.createElement('button'); em.className='btn'; em.textContent='😀 Эмодзи';
 em.onclick=()=>{ const p=document.getElementById('emojipal'); p.style.display=p.style.display==='grid'?'none':'grid'; };
 btns.appendChild(em);
 d.appendChild(btns);
 const pal=document.createElement('div'); pal.id='emojipal'; pal.className='grid3'; pal.style.cssText='display:none;margin-top:10px';
 EMOJIS.forEach(e=>{ const b=document.createElement('div'); b.className='charcard'; b.textContent=e;
  b.onclick=async()=>{ await api('set_emoji',{emoji:e}); toast('Аватар: '+e); renderAll(); }; pal.appendChild(b); });
 d.appendChild(pal);
 el.appendChild(d);
 const cd=document.createElement('div'); cd.className='card';
 cd.innerHTML='<h3>🎞 Коллекция персонажей</h3>';
 const grid=document.createElement('div'); grid.className='chars';
 s.characters.forEach(c=>{ const has=s.chars.includes(c.key);
  const cc=document.createElement('div'); cc.className='charcard'+(has?(s.char===c.key?' on':''):' no');
  cc.innerHTML=c.name.split(' ')[0]+'<div class="cn">'+c.name.replace(/^[^ ]+ /,'')+'</div><div class="cb">'+
   (has?'+'+c.bonus+'%':'🔒 '+c.rar)+'</div>';
  cc.onclick=async()=>{ if(!has){ toast('🔒 Не выбит ('+c.rar+')'); return; }
   await api('set_char',{key:c.key}); haptic(); toast('Активен: '+c.name); renderAll(); };
  grid.appendChild(cc); });
 cd.appendChild(grid); el.appendChild(cd);
}
const EMOJIS = ["⛏️","💎","🔥","👑","🚀","🎩","🦊","🐸","🐲","🤖","🌟","🧙","🥷","🗿","💀","🍀"];
const TABS = [["mine","⛏","Добыча"],["bag","🎒","Рюкзак"],["mines","🗺","Шахты"],["shop","🛒","Магазин"],
 ["auto","🤖","Авто"],["quests","📋","Задания"],["top","🏆","Топ"],["profile","👤","Профиль"]];
const nav=document.getElementById('nav');
TABS.forEach(([id,icon,label])=>{ const b=document.createElement('button'); b.dataset.tab=id;
 b.innerHTML='<i>'+icon+'</i>'+label; b.onclick=()=>setTab(id); nav.appendChild(b); });
document.getElementById('digbtn').onclick=doDig;
document.getElementById('spinbtn').onclick=doSpin;
document.getElementById('bonusbtn').onclick=async()=>{ const j=await api('bonus'); haptic();
 toast(j.err||j.text||'Готово', 3500); if(j.char&&j.char.name) toast('🎉 ПЕРСОНАЖ: '+j.char.name+'!', 4000); renderAll(); };
document.getElementById('casebtn').onclick=async()=>{ const j=await api('case'); haptic();
 toast(j.err||j.text||'Готово', 3500); if(j.char&&j.char.name) toast('🎉 ПЕРСОНАЖ: '+j.char.name+'!', 4000); renderAll(); };
document.getElementById('topmoney').onclick=()=>{ S.topMode='money'; renderTop(); };
document.getElementById('topxp').onclick=()=>{ S.topMode='xp'; renderTop(); };
document.getElementById('promobtn').onclick=async()=>{ const code=document.getElementById('promocode').value.trim();
 if(!code){ toast('Введи код'); return; } const j=await api('promo',{code:code});
 toast(j.err||'🎟 '+j.text); renderAll(); };
(async function boot(){
 if(window.Telegram && Telegram.WebApp){ Telegram.WebApp.ready(); Telegram.WebApp.expand();
  Telegram.WebApp.setHeaderColor('#0e1116'); Telegram.WebApp.setBackgroundColor('#0e1116'); }
 const j = await api('state');
 if(j.err){ document.body.innerHTML = '<div style="padding:40px;text-align:center">Открой игру через кнопку в боте 🙂</div>'; return; }
 renderAll();
 setInterval(()=>{ if(S.st){ S.st.energy_next_sec=Math.max(0,(S.st.energy_next_sec||0)-3);
  if(S.st.energy_next_sec<=0 && S.st.energy<S.st.energy_max){ api('state').then(renderAll); } } }, 3000);
})();
</script></body></html>
"""
PAGE_HTML = HTML_PART1 + HTML_PART2

# ================= БОТ =================
BOT = None
IMG_EXTS = (".gif", ".png", ".jpg", ".jpeg", ".webp")
pending_avatar = set()

def resolve_img(name):
    name = os.path.basename(name)
    p = os.path.join(IMG_DIR, name)
    if os.path.isfile(p):
        return p
    for ext in IMG_EXTS:
        p = os.path.join(IMG_DIR, name + ext)
        if os.path.isfile(p):
            return p
    return None

async def try_send_img(chat_id, name, caption=None):
    u = get_user(chat_id)
    if not u["images_on"]:
        return
    path = resolve_img(name)
    if not path:
        return
    try:
        if path.lower().endswith(".gif"):
            await BOT.send_animation(chat_id, open(path, "rb"), caption=caption)
        else:
            await BOT.send_photo(chat_id, open(path, "rb"), caption=caption)
    except Exception:
        pass

def reply_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⛏ Накопать"), KeyboardButton(text="🎒 Рюкзак")],
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="🎁 Бонус / Кейс")],
        [KeyboardButton(text="🎰 Рулетка"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🏆 Топ"), KeyboardButton(text="🤖 Автосбор")],
    ], resize_keyboard=True)

def prof_text(u):
    lvl, rest, need = level_progress(u["xp"])
    pick = PICKAXE_BY_KEY[u["pickaxe"]]
    with _db_lock, db() as c:
        chars_n = c.execute("SELECT COUNT(*) n FROM chars WHERE user_id=?", (u["user_id"],)).fetchone()["n"]
    char = get_char(u["char_key"]) if u["char_key"] else None
    lines = [
        "👤 %s (ID %d)" % (u["name"], u["user_id"]),
        "🪙 Монеты: %s" % fm(u["money"]),
        "✨ Опыт: %s · Уровень %d (%s/%s)" % (fm(u["xp"]), lvl, fm(rest), fm(need)),
        "⚡ Энергия: %d/%d" % (u["energy"], ENERGY_MAX),
        "⛏ Кирка: %s (сила %d)" % (pick["name"], pick["power"]),
        "🗺 Шахта: %s" % LOCATION_BY_KEY[u["location"]]["name"],
        "🎞 Персонажей: %d" % chars_n,
    ]
    if char:
        lines.append("🤝 Активный персонаж: %s (+%d%%)" % (char["name"], char["bonus"]))
    if u["discount_pct"] and (u["discount_ts"] or 0) > int(time.time()):
        lines.append("🏷 Скидка %d%% на следующую покупку" % u["discount_pct"])
    return "\n".join(lines)

def top_text():
    t = top_users()
    lines = ["🏆 Богатейшие:"]
    for i, r in enumerate(t["money"][:10], 1):
        lines.append("%d. %s — %s 🪙" % (i, r["name"], fm(r["money"])))
    lines.append("")
    lines.append("✨ Опытные:")
    for i, r in enumerate(t["xp"][:10], 1):
        lines.append("%d. %s — ур. %d" % (i, r["name"], r["level"]))
    return "\n".join(lines)

def bag_text(u):
    bag = bag_get(u["user_id"])
    if not bag:
        return "🎒 Рюкзак пуст. Накопай руду командой «⛏ Накопать»."
    lines = ["🎒 Рюкзак:"]
    total = 0
    for k in ORE_KEYS:
        if bag.get(k, 0) > 0:
            total += bag[k] * ORES[k]["price"]
            lines.append("%s — %d шт (по %d 🪙)" % (ORES[k]["name"], bag[k], ORES[k]["price"]))
    lines.append("Всего на %s 🪙 — «/продать всё»" % fm(total))
    return "\n".join(lines)

def register_bot(dp: Dispatcher):
    @dp.message(Command("start", "старт"))
    async def cmd_start(m: Message):
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⛏ Открыть игру", web_app=WebAppInfo(url=APP_URL + "/app"))]] if APP_URL else [],
                                  resize_keyboard=True)
        await m.answer("Привет, %s! 👋\n\nТы в шахтёрском боте: копай руду, собирай персонажей, крути рулетку.\n\n"
                       "Меню под сообщением или кнопка ниже." % (m.from_user.first_name or ""),
                       reply_markup=reply_kb())
        if APP_URL:
            await m.answer("▶️ Открой игру:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⛏ Открыть игру", web_app=WebAppInfo(url=APP_URL + "/app"))]]))
        await try_send_img(m.chat.id, "welcome")

    @dp.message(Command("help"))
    async def cmd_help(m: Message):
        await m.answer("Команды:\n/копать — накопать (тратит заряд энергии)\n/профиль — профиль\n"
                       "/рюкзак — рюкзак\n/продать всё — продать всю руду\n/шахта 1..6 — сменить шахту\n"
                       "/купить <кирка> — stone, iron, gold, diamond, mithril, ruby, legendary\n"
                       "/бонус — бонус раз в 12 ч\n/кейс — кейс раз в 24 ч\n/рулетка <ставка> — с 20 уровня\n"
                       "/персонажи — коллекция\n/персонаж <ключ> — активировать\n"
                       "/авто и /авто_собрать — автосбор\n/перевод <ID> <сумма> — перевод монет (5%)\n"
                       "/аватар — поставить фото из чата аватаркой\n/refund — возврат покупки (15 мин)\n"
                       "/promo КОД — промокод\n/top — топ")

    @dp.message(Command("profile", "профиль"))
    async def cmd_profile(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        await try_send_img(m.chat.id, "profile", prof_text(u))

    @dp.message(Command("top", "топ"))
    async def cmd_top(m: Message):
        await try_send_img(m.chat.id, "top", top_text())

    @dp.message(Command("копать", "mine"))
    async def cmd_mine(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        r = do_mine(u)
        if r.get("err"):
            await m.answer("❌ " + r["err"])
            return
        text = "⛏ Добыто: %s ×%d (+%d опыта)" % (r["ore"], r["qty"], r["xp"])
        if r.get("char"):
            text += "\n🎉 Встреча! Персонаж %s теперь твой!" % r["char"]["name"]
            await try_send_img(m.chat.id, "char_" + r["char"]["key"])
        await m.answer(text)

    @dp.message(Command("рюкзак", "bag"))
    async def cmd_bag(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        await m.answer(bag_text(u))

    @dp.message(Command("продать"))
    async def cmd_sell(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        parts = (m.text or "").split()
        arg = parts[1] if len(parts) > 1 else "всё"
        if arg == "всё":
            r = sell_ores(u)
        else:
            ore = arg if arg in ORES else None
            if not ore:
                await m.answer("❌ Укажи руду: " + ", ".join(ORE_KEYS))
                return
            qty = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            r = sell_ores(u, ore, qty)
        await m.answer(("💰 Продано на %s монет" % fm(r["earned"])) if r.get("ok") else "❌ " + r.get("err", ""))

    @dp.message(Command("купить", "buy"))
    async def cmd_buy(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        parts = (m.text or "").split()
        if len(parts) < 2 or parts[1] not in PICKAXE_BY_KEY:
            await m.answer("❌ Укажи кирку: " + ", ".join(p["key"] for p in PICKAXES))
            return
        r = buy_pickaxe(u, parts[1])
        if r.get("err"):
            await m.answer("❌ " + r["err"])
            return
        await try_send_img(m.chat.id, "pick_" + parts[1],
                           "✅ Куплено: %s за %s монет" % (r["name"], fm(r["price"])))

    @dp.message(Command("шахта"))
    async def cmd_loc(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        parts = (m.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit() or not (1 <= int(parts[1]) <= 6):
            await m.answer("❌ Укажи номер шахты 1..6")
            return
        r = set_location(u, "mine_" + parts[1])
        await m.answer(("🗺 " + LOCATION_BY_KEY["mine_" + parts[1]]["name"]) if r.get("ok") else "❌ " + r["err"])

    @dp.message(Command("бонус"))
    async def cmd_bonus(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        r = claim_bonus(u)
        await try_send_img(m.chat.id, "bonus", ("🎁 " + r["text"]) if r.get("ok") else "❌ " + r["err"])

    @dp.message(Command("кейс"))
    async def cmd_case(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        r = open_case(u)
        if r.get("ok") and r.get("kind") == "char":
            await try_send_img(m.chat.id, "char_" + r["char"]["key"])
        await m.answer(("📦 " + r["text"]) if r.get("ok") else "❌ " + r["err"])

    @dp.message(Command("рулетка"))
    async def cmd_roulette(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        parts = (m.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            await m.answer("❌ Укажи ставку: /рулетка 500")
            return
        r = spin_roulette(u, parts[1])
        if r.get("err"):
            await m.answer("❌ " + r["err"])
            return
        if r["mult"] >= 3:
            await try_send_img(m.chat.id, "jackpot")
        msg = "🎰 ×%s → %s монет" % (r["mult"], fm(r["payout"]))
        if r["mult"] == 0:
            msg = "💀 Мимо! Ставка сгорела"
        await m.answer(msg + "\nБаланс: %s 🪙" % fm(get_user(m.from_user.id)["money"]))

    @dp.message(Command("персонажи"))
    async def cmd_chars(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        with _db_lock, db() as c:
            mine = {r["char_key"] for r in c.execute("SELECT char_key FROM chars WHERE user_id=?", (u["user_id"],))}
        lines = ["🎞 Твоя коллекция: %d/%d" % (len(mine), len(CHARACTERS)), ""]
        for c in CHARACTERS:
            mark = "✅" if c["key"] in mine else "🔒"
            lines.append("%s %s (+%d%%) — %s, шанс %s%%" % (mark, c["name"], c["bonus"], c["rar"], c["chance"]))
        await m.answer("\n".join(lines))

    @dp.message(Command("персонаж"))
    async def cmd_setchar(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        parts = (m.text or "").split()
        if len(parts) < 2:
            await m.answer("❌ Укажи ключ персонажа (см. /персонажи)")
            return
        key = parts[1]
        if not have_char(u["user_id"], key):
            await m.answer("❌ Этот персонаж не выбит")
            return
        u["char_key"] = key
        save_user(u)
        c = get_char(key)
        await m.answer("🤝 Активен: %s (+%d%% к добыче)" % (c["name"], c["bonus"]))

    @dp.message(Command("авто"))
    async def cmd_auto(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        if u["auto_level"] == 0:
            await m.answer("🤖 Автосбор: не куплен. /авто_купить — 5000 монет.\nКаждый уровень: шахта копает каждые %d ч, даже офлайн." % AUTO_INTERVAL_H)
        else:
            waited = int(time.time()) - (u["auto_ts"] or int(time.time()))
            cycles = waited // (AUTO_INTERVAL_H * 3600)
            await m.answer("🤖 Автосбор: уровень %d/%d\nЦиклов накоплено: %d\nЗабрать: /авто_собрать\nУлучшить: /авто_купить (за %s)" %
                           (u["auto_level"], AUTO_MAX_LEVEL, cycles, fm(5000 * (2 ** u["auto_level"]))))

    @dp.message(Command("авто_купить"))
    async def cmd_auto_buy(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        r = buy_auto(u)
        await m.answer(("🤖 Уровень автосбора: %d" % r["level"]) if r.get("ok") else "❌ " + r["err"])

    @dp.message(Command("авто_собрать"))
    async def cmd_auto_collect(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        r = collect_auto(u)
        if r.get("err"):
            await m.answer("❌ " + r["err"])
            return
        got = ", ".join("%s ×%d" % (ORES[k]["name"], q) for k, q in r["got"].items())
        await try_send_img(m.chat.id, "auto_mine", "🤖 Шахта за %d цикла(ов):\n%s" % (r["cycles"], got))

    @dp.message(Command("перевод", "transfer"))
    async def cmd_transfer(m: Message):
        parts = (m.text or "").split()
        to_id, amount = None, None
        if m.reply_to_message and len(parts) >= 2 and parts[1].isdigit():
            to_id, amount = m.reply_to_message.from_user.id, int(parts[1])
        elif len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            to_id, amount = int(parts[1]), int(parts[2])
        if not to_id or not amount:
            await m.answer("❌ Формат: /перевод <ID> <сумма> (или ответом на сообщение: /перевод <сумма>)")
            return
        r = transfer_money(m.from_user.id, to_id, amount)
        if r.get("err"):
            await m.answer("❌ " + r["err"])
            return
        await m.answer("✅ Переведено %s монет (комиссия %s)" % (fm(r["amount"]), fm(r["fee"])))
        try:
            await BOT.send_message(to_id, "🪙 Тебе перевели %s монет от %s!" % (fm(r["amount"]), m.from_user.full_name))
        except Exception:
            pass

    @dp.message(Command("аватар"))
    async def cmd_avatar(m: Message):
        pending_avatar.add(m.from_user.id)
        await m.answer("📷 Пришли фото следующим сообщением — оно станет аватаркой профиля (и будет видно в топе).")

    @dp.message(lambda m: m.from_user.id in pending_avatar and m.photo)
    async def got_avatar(m: Message):
        pending_avatar.discard(m.from_user.id)
        photo = m.photo[-1]
        if (photo.file_size or 0) > 3 * 1024 * 1024:
            await m.answer("❌ Файл больше 3 МБ")
            return
        f = await BOT.get_file(photo.file_id)
        import io
        buf = io.BytesIO()
        await BOT.download_file(f.file_path, destination=buf)
        ext = os.path.splitext(f.file_path or "")[1].lstrip(".") or "jpg"
        if ext not in ("png", "jpg", "jpeg", "webp"):
            ext = "jpg"
        for e in ("png", "jpg", "jpeg", "webp"):
            old = os.path.join(AVATAR_DIR, "%s.%s" % (m.from_user.id, e))
            if os.path.isfile(old):
                os.remove(old)
        with open(os.path.join(AVATAR_DIR, "%s.%s" % (m.from_user.id, ext)), "wb") as fh:
            fh.write(buf.getvalue())
        u = get_user(m.from_user.id, m.from_user.full_name)
        u["avatar_mode"] = "photo"
        save_user(u)
        await m.answer("✅ Аватар обновлён! Виден в профиле и в топе.")

    @dp.message(Command("refund"))
    async def cmd_refund(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        if not u["lp_type"] or int(time.time()) - u["lp_ts"] > REFUND_WINDOW_MIN * 60:
            await m.answer("❌ Возвращать нечего (окно 15 минут после покупки)")
            return
        u["money"] += u["lp_price"]
        if u["lp_type"] == "pick" and u["pickaxe"] == u["lp_key"]:
            order = [x["key"] for x in PICKAXES]
            u["pickaxe"] = order[max(0, order.index(u["lp_key"]) - 1)]
        if u["lp_type"] == "auto":
            u["auto_level"] = max(0, u["auto_level"] - 1)
        u["lp_type"] = ""
        save_user(u)
        await m.answer("↩️ Возврат оформлен (+%s монет)" % fm(u["lp_price"]))

    @dp.message(Command("images_on", "images_off"))
    async def cmd_images(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        u["images_on"] = 1 if m.command() == "images_on" else 0
        save_user(u)
        await m.answer("🖼 Картинки в чате: " + ("вкл" if u["images_on"] else "выкл"))

    @dp.message(Command("promo"))
    async def cmd_promo(m: Message):
        u = get_user(m.from_user.id, m.from_user.full_name)
        parts = (m.text or "").split()
        if len(parts) < 2:
            await m.answer("❌ Формат: /promo КОД")
            return
        r = apply_promo(u, parts[1])
        await try_send_img(m.chat.id, "promo", ("🎟 " + r["text"]) if r.get("ok") else "❌ " + r["err"])

    @dp.message(Command("stats"))
    async def cmd_stats(m: Message):
        if m.from_user.id not in ADMIN_IDS:
            return
        with _db_lock, db() as c:
            n = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
            money = c.execute("SELECT SUM(money) s FROM users").fetchone()["s"] or 0
        await m.answer("📊 Игроков: %d\n🪙 Монет у игроков: %s" % (n, fm(money)))

    @dp.message(Command("genpromo"))
    async def cmd_genpromo(m: Message):
        if m.from_user.id not in ADMIN_IDS:
            return
        parts = (m.text or "").split()
        if len(parts) < 3 or not parts[1].isdigit():
            await m.answer("❌ Формат: /genpromo <активаций> <сумма> [money|xp|ore]")
            return
        uses, value = int(parts[1]), int(parts[2])
        kind = parts[3] if len(parts) > 3 and parts[3] in ("money", "xp", "ore") else "money"
        code = secrets.token_hex(4).upper()
        with _db_lock, db() as c:
            c.execute("INSERT INTO promos(code, uses, kind, value) VALUES(?,?,?,?)", (code, uses, kind, value))
        await m.answer("🎟 Промокод создан: %s\n%s активаций, %s %s" % (code, uses, fm(value), kind))

    @dp.message(Command("myid"))
    async def cmd_myid(m: Message):
        await m.answer("Твой ID: %d" % m.from_user.id)

    @dp.message()
    async def fallback(m: Message):
        if m.text == "⛏ Накопать":
            await cmd_mine(m)
        elif m.text == "🎒 Рюкзак":
            await cmd_bag(m)
        elif m.text == "👤 Профиль":
            await cmd_profile(m)
        elif m.text == "🏆 Топ":
            await cmd_top(m)
        elif m.text == "🎁 Бонус / Кейс":
            u = get_user(m.from_user.id, m.from_user.full_name)
            now = int(time.time())
            await m.answer("🎁 Бонус: %s\n📦 Кейс: %s\n\nКоманды: /бонус, /кейс" %
                           (("готов! /бонус") if now - (u["bonus_ts"] or 0) >= BONUS_CD_H * 3600 else "через " + fmt_left(BONUS_CD_H * 3600 - (now - u["bonus_ts"])),
                            ("готов! /кейс") if now - (u["case_ts"] or 0) >= CASE_CD_H * 3600 else "через " + fmt_left(CASE_CD_H * 3600 - (now - u["case_ts"]))))
        elif m.text == "🛒 Магазин":
            lines = ["🛒 Кирки:"]
            for p in PICKAXES:
                lines.append("%s — %s монет (с %d ур.) ключ: %s" % (p["name"], fm(p["price"]), p["level"], p["key"]))
            lines.append("\n⚡ Восстановить энергию — %d монет (в приложении)" % ENERGY_REFILL_PRICE)
            await m.answer("\n".join(lines))
        elif m.text == "🎰 Рулетка":
            await m.answer("🎰 Рулетка: /рулетка <ставка>\nСектора: " +
                           ", ".join("×%s (%s%%)" % (m2, ch) for m2, ch in ROULETTE_SECTORS) +
                           "\nС %d уровня, без кулдауна." % ROULETTE_MIN_LEVEL)
        elif m.text == "🤖 Автосбор":
            await cmd_auto(m)

# ================= ЗАПУСК =================
class PrivateOnly(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None)
        if chat is not None and chat.type != "private":
            return
        return await handler(event, data)

async def auto_notify_loop():
    last = {}
    while True:
        try:
            await asyncio.sleep(300)
            now = int(time.time())
            with _db_lock, db() as c:
                rows = [dict(r) for r in c.execute("SELECT user_id, auto_ts FROM users WHERE auto_level>0")]
            for r in rows:
                due = (r["auto_ts"] or now) + AUTO_INTERVAL_H * 3600 <= now
                if due and now - last.get(r["user_id"], 0) >= AUTO_INTERVAL_H * 3600:
                    last[r["user_id"]] = now
                    try:
                        await BOT.send_message(r["user_id"], "🤖 Шахта накопала руду! Забери: /авто_собрать")
                    except Exception:
                        pass
        except Exception:
            pass

async def main():
    global BOT
    if not TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN! Установи переменную окружения BOT_TOKEN.")
    init_db()
    BOT = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.message.middleware(PrivateOnly())
    register_bot(dp)
    app = aio_web.Application()
    app.router.add_get("/app", h_app)
    app.router.add_get("/img/{name}", h_img)
    app.router.add_get("/avatars/{name}", h_avatar_file)
    app.router.add_post("/api/{action}", api_handler)
    app.router.add_post("/api/avatar", h_avatar_upload)
    runner = aio_web.AppRunner(app)
    await runner.setup()
    site = aio_web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print("Mini App:", (APP_URL or "?") + "/app")
    print("Bot polling: запущен")
    asyncio.create_task(auto_notify_loop())
    await dp.start_polling(BOT)

if __name__ == "__main__":
    init_db()
    asyncio.run(main())
