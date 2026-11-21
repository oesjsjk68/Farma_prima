# web.py — веб-панель шахтёрского бота (запускать рядом с main.py)
import os
import random
import secrets
import sqlite3
import json
import hashlib
import hmac
from datetime import datetime, timedelta
from urllib.parse import parse_qsl
from aiohttp import web

# ================= НАСТРОЙКИ =================
PORT = int(os.getenv("PORT", 8080))
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
AUTO_INTERVAL_HOURS = 3
AUTO_MAX_LEVEL = 10
ROULETTE_COOLDOWN_SEC = 30
ROULETTE_MIN_LEVEL = 20
ROULETTE_MIN_BET = 10
ROULETTE_MAX_BET = 100000
TRANSFER_MIN = 100

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
DB_NAME = os.path.join(DATA_DIR, "bot_db.sqlite")
if not os.path.exists(DB_NAME):
    alt = os.path.join(SCRIPT_DIR, "bot_db.sqlite")
    if os.path.exists(alt):
        DB_NAME = alt
# если база ещё не создана ботом — панель сама готовит папку data
if not os.path.exists(DB_NAME):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError:
        pass

IMAGES_DIR = os.path.join(SCRIPT_DIR, "images")
IMG_HOST = os.getenv("IMG_HOST", "")


def img_url(name):
    if IMG_HOST:
        return IMG_HOST.rstrip("/") + "/" + name
    return "/img/" + name


# ================= КОНТЕНТ =================
CHAR_KEYWORDS = [
    ("подруг", "char_podrugi.jpg"), ("казуя", "char_kazuya.jpg"),
    ("мину", "char_minu.jpg"), ("усопп", "char_usopp.jpg"),
    ("синдзи", "char_shinji.jpg"), ("мумен", "char_mumen.jpg"),
    ("тен тен", "char_tenten.jpg"), ("багги", "char_buggy.jpg"),
    ("юкитэру", "char_yukiteru.jpg"), ("юкитеру", "char_yukiteru.jpg"),
    ("кадзума", "char_kazuma.jpg"), ("луффи", "char_luffy.jpg"),
    ("джин ву", "char_jinwoo.jpg"), ("кинг", "char_king.jpg"),
    ("лелуш", "char_lelouch.jpg"), ("монома", "char_monoma.jpg"),
    ("рейген", "char_reigen.jpg"), ("ичиго", "char_ichigo.jpg"),
    ("курапика", "char_kurapika.jpg"), ("киллуа", "char_killua.jpg"),
    ("годжо", "char_gojo.jpg"), ("адам", "char_adam.jpg"),
    ("симон", "char_simon.jpg"), ("алукард", "char_alucard.jpg"),
    ("моб", "char_mob.jpg"),
]


def char_img(name):
    n = (name or "").lower()
    for kw, f in CHAR_KEYWORDS:
        if kw in n:
            return img_url(f)
    return None


RARITY_COLORS = {
    "обычный": "#9aa3ad", "редкий": "#4aa3ff", "эпический": "#b46bff",
    "легендарный": "#ffc400", "мифический": "#ff5c5c", "уникальный": "#00e5c0",
}

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
ORE_KEYS = list(ORES.keys())

PICKAXES = [
    {"key": "wood",      "name": "🪵 Деревянная",   "power": 0,   "price": 0,         "level": 1},
    {"key": "stone",     "name": "⛏️ Каменная",     "power": 3,   "price": 5000,      "level": 10},
    {"key": "iron",      "name": "⛏️ Железная",     "power": 10,  "price": 250000,    "level": 20},
    {"key": "gold",      "name": "⛏️ Золотая",      "power": 25,  "price": 1000000,   "level": 35},
    {"key": "diamond",   "name": "⛏️ Алмазная",     "power": 50,  "price": 5000000,   "level": 50},
    {"key": "mithril",   "name": "⛏️ Мифриловая",   "power": 80,  "price": 25000000,  "level": 70},
    {"key": "ruby",      "name": "⛏️ Рубиновая",    "power": 110, "price": 100000000, "level": 90},
    {"key": "legendary", "name": "⛏️ ЛЕГЕНДАРНАЯ",  "power": 150, "price": 500000000, "level": 100},
]
PICKAXE_BY_KEY = {p["key"]: p for p in PICKAXES}

LOCATIONS = [
    {"key": "mine_1", "name": "⛏️ Старая шахта",       "mult": 1.0, "min_level": 1},
    {"key": "mine_2", "name": "🗻 Глубокие штольни",   "mult": 1.5, "min_level": 15},
    {"key": "mine_3", "name": "🌋 Огненные пещеры",    "mult": 2.0, "min_level": 30},
    {"key": "mine_4", "name": "❄️ Ледяные гроты",      "mult": 2.5, "min_level": 45},
    {"key": "mine_5", "name": "✨ Зачарованные копи",   "mult": 3.0, "min_level": 60},
    {"key": "mine_6", "name": "🔮 Мифриловые глубины", "mult": 4.0, "min_level": 80},
]

ROULETTE_SECTORS = [
    {"name": "💥 Джекпот x5!",        "chance": 0.02, "mult": 5.0},
    {"name": "🔥 Крупный выигрыш x3", "chance": 0.08, "mult": 3.0},
    {"name": "✅ Выигрыш x2",          "chance": 0.20, "mult": 2.0},
    {"name": "➖ Возврат ставки",      "chance": 0.15, "mult": 1.0},
    {"name": "❌ Проигрыш",            "chance": 0.55, "mult": 0.0},
]

PROMO_TYPES = {
    "money": "монет", "xp": "опыта",
    "stone": "камня", "iron": "железной руды", "copper": "медной руды",
    "silver": "серебра", "gold": "золотой руды",
    "ruby": "рубинов", "diamond": "алмазов", "mithril": "мифрила",
}

CASE_REWARDS = [
    {"chance": 0.300, "coins": 100,    "label": "🪙 100 монет"},
    {"chance": 0.250, "coins": 500,    "label": "🪙 500 монет"},
    {"chance": 0.200, "coins": 1000,   "label": "🪙 1 000 монет"},
    {"chance": 0.120, "coins": 2500,   "label": "🪙 2 500 монет"},
    {"chance": 0.080, "coins": 5000,   "label": "🪙 5 000 монет"},
    {"chance": 0.035, "coins": 10000,  "label": "🪙 10 000 монет"},
    {"chance": 0.015, "coins": 50000,  "label": "💥 ДЖЕКПОТ 50 000 монет!", "jackpot": True},
]

QUESTS = {"mine": 20, "sell": 3, "spin": 5}
QUEST_REWARD = 6500
QUEST_TITLES = {
    "mine": "⛏️ Накопать руду 20 раз",
    "sell": "💰 Продать руду 3 раза",
    "spin": "🎲 Крутить рулетку 5 раз",
}

MINE_CHANCES = {
    "iron":    (0.20, 200, 100),
    "copper":  (0.10, 400, 200),
    "silver":  (0.06, 600, 300),
    "gold":    (0.05, 800, 400),
    "ruby":    (0.03, 1000, 600),
    "diamond": (0.02, 1500, 900),
    "mithril": (0.008, 2500, 1500),
}

DISCOUNT_PER_PURCHASE = 1
DISCOUNT_MAX = 15

tokens = {}
roulette_cd = {}


# ================= БАЗА =================
def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_columns():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(users)")
        cols = {r[1] for r in cur.fetchall()}
        for col in ["ore_silver", "ore_ruby", "ore_diamond", "ore_mithril",
                    "q_date", "q_mine", "q_sell", "q_spin", "q_claimed",
                    "auto_level", "auto_last_at", "location_key", "images_on"]:
            if col not in cols:
                if col in ("q_date", "auto_last_at"):
                    cur.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT ''")
                else:
                    cur.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        cur.execute("""CREATE TABLE IF NOT EXISTS web_codes (
            code TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS web_sessions (
            token TEXT PRIMARY KEY, user_id INTEGER, expires_at TEXT)""")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()


ensure_columns()


def xp_needed_for_next_level(level):
    return level * 100


def auto_next_price(lvl):
    return 5000 * (2 ** lvl)


def get_user(user_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_user(user_id, **kwargs):
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    conn = get_conn()
    conn.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()


def get_prices():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT ore_key, price FROM prices")
        result = dict(cur.fetchall())
    except sqlite3.OperationalError:
        result = {}
    conn.close()
    return result


def get_setting(key, default):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    try:
        return int(row[0])
    except (TypeError, ValueError, IndexError):
        return default


def get_characters(user_id):
    try:
        conn = get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM characters WHERE user_id = ?", (user_id,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_discount(user_id):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM purchase_history WHERE user_id = ? AND refunded = 0", (user_id,))
        count = cur.fetchone()[0]
    except sqlite3.OperationalError:
        count = 0
    conn.close()
    base = min(DISCOUNT_MAX, count * DISCOUNT_PER_PURCHASE)
    jackpot = 0
    user = get_user(user_id)
    if user and user.get("jackpot_until"):
        try:
            until = datetime.fromisoformat(user["jackpot_until"])
            if datetime.now() <= until:
                jackpot = int(user.get("jackpot_discount") or 0)
        except ValueError:
            pass
    return base + jackpot, base, jackpot


def consume_jackpot(user_id):
    try:
        update_user(user_id, jackpot_discount=0, jackpot_until=None)
    except sqlite3.OperationalError:
        pass


def can_mine(user):
    if not user.get("last_mine_at"):
        return True
    try:
        last = datetime.fromisoformat(user["last_mine_at"])
    except ValueError:
        return True
    return datetime.now() >= last + timedelta(seconds=3)


def mine_seconds_left(user):
    try:
        last = datetime.fromisoformat(user["last_mine_at"])
    except (ValueError, TypeError):
        return 0
    end = last + timedelta(seconds=3)
    return max(0, int((end - datetime.now()).total_seconds()))


def can_bonus(user):
    if not user.get("last_bonus_at"):
        return True
    try:
        last = datetime.fromisoformat(user["last_bonus_at"])
    except ValueError:
        return True
    hours = get_setting("bonus_hours", 12)
    return datetime.now() >= last + timedelta(hours=hours)


def bonus_time_left(user):
    try:
        last = datetime.fromisoformat(user["last_bonus_at"])
    except (ValueError, TypeError):
        return 0, 0
    hours = get_setting("bonus_hours", 12)
    end = last + timedelta(hours=hours)
    total_min = max(0, int((end - datetime.now()).total_seconds() // 60))
    return total_min // 60, total_min % 60


def case_ready(user):
    hours = get_setting("case_hours", 24)
    if not user.get("last_case_at"):
        return True, 0, 0
    try:
        last = datetime.fromisoformat(user["last_case_at"])
    except (ValueError, TypeError):
        return True, 0, 0
    end = last + timedelta(hours=hours)
    if datetime.now() >= end:
        return True, 0, 0
    total_min = int((end - datetime.now()).total_seconds() // 60)
    return False, total_min // 60, total_min % 60


def add_xp(user_id, user, gained):
    new_xp = int(user["xp"]) + gained
    new_level = int(user["level"])
    levelups = 0
    while new_xp >= xp_needed_for_next_level(new_level):
        new_xp -= xp_needed_for_next_level(new_level)
        new_level += 1
        levelups += 1
    update_user(user_id, xp=new_xp, level=new_level)
    return new_level, levelups


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def quest_state(user):
    if (user.get("q_date") or "") != today_str():
        return {"mine": 0, "sell": 0, "spin": 0, "claimed": False}
    return {
        "mine": int(user.get("q_mine") or 0),
        "sell": int(user.get("q_sell") or 0),
        "spin": int(user.get("q_spin") or 0),
        "claimed": bool(int(user.get("q_claimed") or 0)),
    }


def bump_quest(user_id, user, key):
    today = today_str()
    if (user.get("q_date") or "") != today:
        update_user(user_id, q_date=today, q_mine=0, q_sell=0, q_spin=0, q_claimed=0)
        user = get_user(user_id) or user
    col = "q_" + key
    update_user(user_id, **{col: int(user.get(col) or 0) + 1})


def char_bonus_pct(user_id):
    total = 0.0
    for c in get_characters(user_id):
        try:
            total += float(c.get("bonus_pct") or 0)
        except (TypeError, ValueError):
            pass
    return min(100.0, total)


def auth_user(request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return None, None
    user_id = tokens.get(token)
    if user_id is None:
        try:
            conn = get_conn()
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT token, user_id, expires_at FROM web_sessions WHERE token = ?", (token,))
            row = cur.fetchone()
            conn.close()
            if row and row["expires_at"] > datetime.now().isoformat():
                user_id = row["user_id"]
        except sqlite3.OperationalError:
            pass
    if not user_id:
        return None, None
    return get_user(user_id), token


def api_json(data, status=200):
    return web.json_response(data, status=status)


def verify_init_data(init_data):
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.get("hash")
        if not received_hash:
            return None
        check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parse_qsl(init_data, keep_blank_values=True)) if k != "hash")
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        user = json.loads(pairs["user"])
        return int(user["id"])
    except Exception:
        return None


# ================= API: ВХОД =================
async def api_login(request):
    data = await request.json()
    code = str(data.get("code", "")).strip()
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, created_at FROM web_codes WHERE code = ?", (code,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    if not row:
        return api_json({"ok": False, "error": "Код не найден. Попроси у бота новый: /код"}, 401)
    try:
        fresh = datetime.now() - datetime.fromisoformat(row["created_at"]) <= timedelta(minutes=15)
    except ValueError:
        fresh = False
    if not fresh:
        return api_json({"ok": False, "error": "Код устарел. Попроси новый: /код"}, 401)
    conn = get_conn()
    conn.execute("DELETE FROM web_codes WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    token = secrets.token_hex(16)
    tokens[token] = row["user_id"]
    return api_json({"ok": True, "token": token})


async def api_tg_auth(request):
    data = await request.json()
    user_id = verify_init_data(data.get("initData") or "")
    if not user_id:
        return api_json({"ok": False}, status=403)
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, str(user_id)))
    conn.commit()
    conn.close()
    token = secrets.token_hex(16)
    tokens[token] = user_id
    return api_json({"ok": True, "token": token})


# ================= API: СОСТОЯНИЕ =================
async def api_state(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    prices = get_prices()
    backpack = [{"key": k, "name": ORES[k]["name"], "count": int(user.get(f"ore_{k}", 0) or 0),
                 "price": prices.get(k, ORES[k]["price"])} for k in ORE_KEYS]
    total_bag = sum(x["count"] * x["price"] for x in backpack)
    needed = xp_needed_for_next_level(user["level"])
    pick = PICKAXE_BY_KEY.get(user.get("pickaxe_key", "wood"), PICKAXES[0])

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, balance, level FROM users ORDER BY balance DESC, level DESC LIMIT 10")
    top_rich = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT username, level FROM users ORDER BY level DESC, balance DESC LIMIT 10")
    top_level = [dict(r) for r in cur.fetchall()]
    conn.close()

    if can_bonus(user):
        bonus_left = "доступен"
    else:
        h, m = bonus_time_left(user)
        bonus_left = f"{h} ч {m} мин"

    loc_key = user.get("location_key") or "mine_1"
    cur_loc = next((l for l in LOCATIONS if l["key"] == loc_key), LOCATIONS[0])
    locations = [{"key": l["key"], "name": l["name"], "mult": l["mult"],
                  "min_level": l["min_level"], "img": img_url(l["key"] + ".jpg"),
                  "current": l["key"] == loc_key,
                  "available": user["level"] >= l["min_level"]} for l in LOCATIONS]

    auto_lvl = int(user.get("auto_level") or 0)
    mins_left = 0
    if auto_lvl > 0 and user.get("auto_last_at"):
        try:
            end = datetime.fromisoformat(user["auto_last_at"]) + timedelta(hours=AUTO_INTERVAL_HOURS)
            mins_left = max(0, int((end - datetime.now()).total_seconds() // 60))
        except ValueError:
            mins_left = 0
    auto_price = auto_next_price(auto_lvl) if auto_lvl < AUTO_MAX_LEVEL else None

    chars_out = []
    for c in get_characters(user["user_id"]):
        chars_out.append({"name": c.get("name", "?"),
                          "rarity": c.get("rarity", ""),
                          "bonus_pct": c.get("bonus_pct", 0),
                          "img": char_img(c.get("name", "")),
                          "color": RARITY_COLORS.get(c.get("rarity", ""), "#9aa3ad")})

    qs = quest_state(user)
    quests = {"items": [{"key": k, "title": QUEST_TITLES[k], "done": qs[k],
                         "target": QUESTS[k]} for k in QUESTS],
              "claimed": qs["claimed"], "reward": QUEST_REWARD}

    case_ok, ch, cm = case_ready(user)
    disc, base, jp = get_discount(user["user_id"])
    r_left = 0
    now_ts = datetime.now().timestamp()
    if now_ts - roulette_cd.get(token, 0) < ROULETTE_COOLDOWN_SEC:
        r_left = int(ROULETTE_COOLDOWN_SEC - (now_ts - roulette_cd.get(token, 0)))

    return api_json({
        "ok": True,
        "username": user.get("username", ""),
        "balance": user["balance"],
        "xp": user["xp"], "xp_needed": needed, "level": user["level"],
        "pickaxe": pick["name"], "pickaxe_power": pick["power"],
        "backpack": backpack, "bag_value": total_bag,
        "mine_ready": can_mine(user), "mine_wait": mine_seconds_left(user),
        "bonus_ready": can_bonus(user), "bonus_left": bonus_left,
        "shop": PICKAXES,
        "discount": disc,
        "top_rich": top_rich, "top_level": top_level,
        "roulette_open": user["level"] >= ROULETTE_MIN_LEVEL,
        "roulette_min_level": ROULETTE_MIN_LEVEL,
        "roulette_wait": r_left,
        "locations": locations, "location": cur_loc["name"],
        "banner": img_url("banner.jpg"),
        "auto_level": auto_lvl,
        "auto_next_price": auto_price,
        "auto_mins_left": mins_left if auto_lvl > 0 else None,
        "characters": chars_out,
        "char_bonus": char_bonus_pct(user["user_id"]),
        "quests": quests,
        "case_ready": case_ok, "case_left": f"{ch} ч {cm} мин" if not case_ok else "",
    })


# ================= API: ДЕЙСТВИЯ =================
async def api_mine(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    if not can_mine(user):
        return api_json({"ok": False, "error": f"Подожди ещё {mine_seconds_left(user)} сек."}, 429)
    loc_key = user.get("location_key") or "mine_1"
    loc = next((l for l in LOCATIONS if l["key"] == loc_key), LOCATIONS[0])
    mult = loc["mult"] * (1.0 + char_bonus_pct(user["user_id"]) / 100.0)
    pick = PICKAXE_BY_KEY.get(user.get("pickaxe_key", "wood"), PICKAXES[0])
    power = pick["power"]
    lvl = user["level"]

    counts = {"stone": int((random.randint(2, 4) + power // 10 + lvl - 1) * mult)}
    for key, (base, pd, ld) in MINE_CHANCES.items():
        if random.random() < base + power / pd + (lvl - 1) / ld:
            counts[key] = int(random.randint(1, 2) * mult)
        else:
            counts[key] = 0
    total_xp = sum(counts[k] * ORES[k]["xp"] for k in ORE_KEYS)
    updates = {f"ore_{k}": int(user.get(f"ore_{k}", 0) or 0) + counts[k] for k in ORE_KEYS}
    updates["last_mine_at"] = datetime.now().isoformat()
    update_user(user["user_id"], **updates)
    new_level, levelups = add_xp(user["user_id"], user, total_xp)
    bump_quest(user["user_id"], user, "mine")
    got = [{"name": ORES[k]["name"], "count": counts[k]} for k in ORE_KEYS if counts[k] > 0]
    return api_json({"ok": True, "got": got, "xp": total_xp,
                     "levelup": levelups, "level": new_level,
                     "location": loc["name"], "img": img_url(loc["key"] + ".jpg")})


async def api_sell(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    prices = get_prices()
    total = 0
    lines = []
    for k in ORE_KEYS:
        cnt = int(user.get(f"ore_{k}", 0) or 0)
        if cnt > 0:
            money = cnt * prices.get(k, ORES[k]["price"])
            lines.append(f"{ORES[k]['name']} × {cnt} = {money}")
            total += money
    if total == 0:
        return api_json({"ok": False, "error": "Рюкзак пуст!"})
    updates = {f"ore_{k}": 0 for k in ORE_KEYS}
    updates["balance"] = user["balance"] + total
    update_user(user["user_id"], **updates)
    bump_quest(user["user_id"], user, "sell")
    return api_json({"ok": True, "total": total, "lines": lines})


async def api_bonus(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    if not can_bonus(user):
        h, m = bonus_time_left(user)
        return api_json({"ok": False, "error": f"Бонус через {h} ч {m} мин"})
    amount = get_setting("bonus_amount", 5000)
    update_user(user["user_id"], balance=user["balance"] + amount,
                last_bonus_at=datetime.now().isoformat())
    return api_json({"ok": True, "amount": amount})


async def api_roulette(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    if user["level"] < ROULETTE_MIN_LEVEL:
        return api_json({"ok": False, "error": f"Рулетка откроется на {ROULETTE_MIN_LEVEL} уровне"})
    data = await request.json()
    bet = data.get("bet")
    if bet is None:
        now = datetime.now().timestamp()
        left = roulette_cd.get(token, 0)
        if now - left < ROULETTE_COOLDOWN_SEC:
            return api_json({"ok": False, "error": f"Подожди ещё {int(ROULETTE_COOLDOWN_SEC - (now - left))} сек."})
        return api_json({"ok": True, "prompt": True})
    try:
        bet = int(bet)
    except (TypeError, ValueError):
        return api_json({"ok": False, "error": "Ставка — число"})
    if not (ROULETTE_MIN_BET <= bet <= ROULETTE_MAX_BET):
        return api_json({"ok": False, "error": f"Ставка от {ROULETTE_MIN_BET} до {ROULETTE_MAX_BET}"})
    if user["balance"] < bet:
        return api_json({"ok": False, "error": f"Не хватает монет: у тебя {user['balance']}"})
    now = datetime.now().timestamp()
    if now - roulette_cd.get(token, 0) < ROULETTE_COOLDOWN_SEC:
        return api_json({"ok": False, "error": f"Подожди ещё {int(ROULETTE_COOLDOWN_SEC - (now - roulette_cd[token]))} сек."})
    roll = random.random()
    cum = 0.0
    idx = len(ROULETTE_SECTORS) - 1
    for i, s in enumerate(ROULETTE_SECTORS):
        cum += s["chance"]
        if roll < cum:
            idx = i
            break
    sector = ROULETTE_SECTORS[idx]
    roulette_cd[token] = now
    win = int(bet * sector["mult"])
    delta = win - bet
    new_balance = user["balance"] + delta
    update_user(user["user_id"], balance=new_balance)
    bump_quest(user["user_id"], user, "spin")
    return api_json({"ok": True, "idx": idx, "sector": sector["name"], "bet": bet,
                     "win": win, "delta": delta, "balance": new_balance,
                     "jackpot": bool(sector.get("jackpot", False)),
                     "mult": sector["mult"]})


async def api_buy(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    data = await request.json()
    key = str(data.get("pickaxe", ""))
    pick = PICKAXE_BY_KEY.get(key)
    if not pick or pick["price"] <= 0:
        return api_json({"ok": False, "error": "Такой кирки нет"})
    if user["level"] < pick["level"]:
        return api_json({"ok": False, "error": f"Нужен {pick['level']} уровень"})
    disc, _, _ = get_discount(user["user_id"])
    price = max(1, pick["price"] * (100 - disc) // 100)
    if user["balance"] < price:
        return api_json({"ok": False, "error": f"Не хватает монет: нужно {price}, у тебя {user['balance']}"})
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO purchase_history (user_id, pickaxe_key, price, refunded, timestamp) VALUES (?, ?, ?, 0, ?)",
                    (user["user_id"], key, price, datetime.now().isoformat()))
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    consume_jackpot(user["user_id"])
    update_user(user["user_id"], balance=user["balance"] - price, pickaxe_key=key)
    return api_json({"ok": True, "price": price, "discount": disc, "pickaxe": pick["name"]})


async def api_location(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    data = await request.json()
    key = str(data.get("key", ""))
    loc = next((l for l in LOCATIONS if l["key"] == key), None)
    if not loc:
        return api_json({"ok": False, "error": "Локация не найдена"})
    if user["level"] < loc["min_level"]:
        return api_json({"ok": False, "error": f"Нужен {loc['min_level']} уровень"})
    update_user(user["user_id"], location_key=key)
    return api_json({"ok": True, "location": loc["name"]})


async def api_auto(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    lvl = int(user.get("auto_level") or 0)
    if lvl >= AUTO_MAX_LEVEL:
        return api_json({"ok": False, "error": "Максимальный уровень автосбора"})
    price = auto_next_price(lvl)
    if user["balance"] < price:
        return api_json({"ok": False, "error": f"Не хватает монет: нужно {price}"})
    update_user(user["user_id"], balance=user["balance"] - price,
                auto_level=lvl + 1, auto_last_at=datetime.now().isoformat())
    return api_json({"ok": True, "level": lvl + 1, "price": price})


async def api_case(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    ok, ch, cm = case_ready(user)
    if not ok:
        return api_json({"ok": False, "error": f"Кейс будет через {ch} ч {cm} мин"})
    roll = random.random()
    cum = 0.0
    reward = CASE_REWARDS[-1]
    for r in CASE_REWARDS:
        cum += r["chance"]
        if roll < cum:
            reward = r
            break
    upd = {"last_case_at": datetime.now().isoformat()}
    if reward.get("jackpot"):
        upd["jackpot_discount"] = 50
        upd["jackpot_until"] = (datetime.now() + timedelta(hours=24)).isoformat()
    else:
        upd["balance"] = user["balance"] + reward["coins"]
    update_user(user["user_id"], **upd)
    return api_json({"ok": True, "label": reward["label"], "coins": reward["coins"],
                     "jackpot": bool(reward.get("jackpot"))})


async def api_transfer(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    data = await request.json()
    target = str(data.get("target", "")).strip()
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return api_json({"ok": False, "error": "Сумма — число"})
    if not target:
        return api_json({"ok": False, "error": "Укажи получателя: ник или ID"})
    if amount < TRANSFER_MIN:
        return api_json({"ok": False, "error": f"Минимум {TRANSFER_MIN} монет"})
    if user["balance"] < amount:
        return api_json({"ok": False, "error": f"Не хватает монет: у тебя {user['balance']}"})
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if target.isdigit():
        cur.execute("SELECT user_id, username FROM users WHERE user_id = ?", (int(target),))
    else:
        cur.execute("SELECT user_id, username FROM users WHERE username = ?", (target,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return api_json({"ok": False, "error": "Игрок не найден"})
    if row["user_id"] == user["user_id"]:
        return api_json({"ok": False, "error": "Нельзя перевести самому себе"})
    conn = get_conn()
    conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user["user_id"]))
    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, row["user_id"]))
    conn.commit()
    conn.close()
    return api_json({"ok": True, "to": row["username"] or str(row["user_id"]), "amount": amount})


async def api_promo(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    data = await request.json()
    code = str(data.get("code", "")).strip().upper()
    if not code:
        return api_json({"ok": False, "error": "Введи промокод"})
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT amount, uses, type FROM promos WHERE code = ?", (code,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    if not row:
        conn.close()
        return api_json({"ok": False, "error": f"Промокод «{code}» не найден"})
    ptype = row["type"] or "money"
    if int(row["uses"]) <= 0:
        conn.close()
        return api_json({"ok": False, "error": "Промокод уже исчерпан"})
    cur.execute("SELECT 1 FROM promo_users WHERE user_id = ? AND code = ?", (user["user_id"], code))
    if cur.fetchone():
        conn.close()
        return api_json({"ok": False, "error": "Ты уже активировал этот промокод"})
    cur.execute("UPDATE promos SET uses = uses - 1 WHERE code = ?", (code,))
    cur.execute("INSERT INTO promo_users (user_id, code) VALUES (?, ?)", (user["user_id"], code))
    conn.commit()
    conn.close()
    amount = int(row["amount"])
    if ptype == "money":
        update_user(user["user_id"], balance=user["balance"] + amount)
    elif ptype == "xp":
        add_xp(user["user_id"], user, amount)
    elif ptype in ORE_KEYS:
        conn = get_conn()
        conn.execute(f"UPDATE users SET ore_{ptype} = ore_{ptype} + ? WHERE user_id = ?", (amount, user["user_id"]))
        conn.commit()
        conn.close()
    return api_json({"ok": True, "text": f"+{amount} {PROMO_TYPES.get(ptype, ptype)}"})


async def api_claim(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    qs = quest_state(user)
    if qs["claimed"]:
        return api_json({"ok": False, "error": "Награда уже получена"})
    if any(qs[k] < QUESTS[k] for k in QUESTS):
        return api_json({"ok": False, "error": "Задания ещё не выполнены"})
    update_user(user["user_id"], balance=user["balance"] + QUEST_REWARD, q_claimed=1)
    return api_json({"ok": True, "reward": QUEST_REWARD})


HTML_PAGE = (
'<!DOCTYPE html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">\n<title>⛏️ Шахта — панель</title>\n<style>\n:root{\n  --bg:#0b0e14; --card:#151a24; --card2:#1b2230; --line:#263042;\n  --text:#e8edf4; --mut:#8b96a8; --acc:#ffc400; --acc2:#4aa3ff;\n  --ok:#2ecc71; --bad:#ff5c5c; --grad:linear-gradient(135deg,#ffc400,#ff8a3c);\n}\n*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}\nbody{background:var(--bg);color:var(--text);font-family:\'Segoe UI\',system-ui,sans-serif;min-height:100vh}\n#login{max-width:380px;margin:14vh auto 0;padding:0 16px;text-align:center}\n#login .logo{font-size:56px}\n#login h1{font-size:22px;margin:10px 0 4px}\n#login p{color:var(--mut);font-size:14px;margin-bottom:20px}\n#login input{width:100%;padding:14px;border-radius:12px;border:1px solid var(--line);\n  background:var(--card2);color:var(--text);font-size:20px;text-align:center;letter-spacing:6px;outline:none}\n#login button{width:100%;margin-top:12px;padding:14px;border:none;border-radius:12px;\n  background:var(--grad);color:#1a1205;font-weight:700;font-size:16px;cursor:pointer}\n#login .err{color:var(--bad);font-size:13px;margin-top:10px;min-height:18px}\n#app{display:none;max-width:520px;margin:0 auto;padding-bottom:24px}\nheader{position:sticky;top:0;z-index:10;background:rgba(11,14,20,.92);backdrop-filter:blur(8px);\n  padding:10px 14px;border-bottom:1px solid var(--line)}\n.hrow{display:flex;align-items:center;justify-content:space-between;gap:8px}\n.huser{font-weight:600;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n.hbal{font-size:18px;font-weight:800;color:var(--acc);white-space:nowrap}\n.hlvl{color:var(--mut);font-size:12px}\n.xpbar{height:5px;border-radius:3px;background:var(--card2);margin-top:7px;overflow:hidden}\n.xpbar div{height:100%;background:var(--grad);border-radius:3px;transition:width .4s}\n.hpick{font-size:12px;color:var(--mut);margin-top:5px}\nnav{display:flex;gap:6px;overflow-x:auto;padding:10px 12px 2px;scrollbar-width:none}\nnav::-webkit-scrollbar{display:none}\nnav button{flex-shrink:0;padding:8px 14px;border-radius:20px;border:1px solid var(--line);\n  background:var(--card);color:var(--mut);font-size:13px;cursor:pointer;white-space:nowrap}\nnav button.on{background:var(--grad);color:#1a1205;font-weight:700;border-color:transparent}\nmain{padding:12px 14px}\n.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin-bottom:12px}\n.card h3{font-size:15px;margin-bottom:10px}\n.btn{display:block;width:100%;padding:13px;border:none;border-radius:12px;\n  background:var(--grad);color:#1a1205;font-weight:700;font-size:15px;cursor:pointer;margin-top:10px}\n.btn:disabled{opacity:.45;cursor:default}\n.btn.ghost{background:var(--card2);color:var(--text);border:1px solid var(--line)}\n.btn.blue{background:linear-gradient(135deg,#4aa3ff,#3d7bff);color:#fff}\n.muted{color:var(--mut);font-size:13px}\n.row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 0;border-bottom:1px solid var(--line)}\n.row:last-child{border-bottom:none}\n.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}\n.shopit{background:var(--card2);border:1px solid var(--line);border-radius:14px;padding:12px}\n.shopit .nm{font-weight:600;font-size:14px}\n.shopit .pw{color:var(--acc2);font-size:12px;margin:4px 0}\n.shopit .pr{font-size:13px;color:var(--mut)}\n.shopit.own{border-color:var(--ok)}\n.shopit.cur{border-color:var(--acc)}\n.locit{display:flex;gap:10px;align-items:center;background:var(--card2);border:1px solid var(--line);\n  border-radius:14px;padding:10px;margin-bottom:8px;cursor:pointer}\n.locit img{width:56px;height:56px;border-radius:10px;object-fit:cover;background:#222}\n.locit .nm{font-weight:600;font-size:14px}\n.locit .mt{color:var(--acc);font-size:12px}\n.locit.cur{border-color:var(--acc)}\n.locit.lock{opacity:.45}\n/* РУЛЕТКА */\n.wheelbox{display:flex;flex-direction:column;align-items:center;padding:6px 0}\n.wheelwrap{position:relative;width:270px;height:270px}\n#wheel{width:270px;height:270px;border-radius:50%;position:relative;\n  border:6px solid #2a3450;box-shadow:0 0 30px rgba(255,196,0,.15) inset;\n  transition:transform 4.2s cubic-bezier(.15,.75,.15,1)}\n.wlab{position:absolute;left:50%;top:50%;font-size:13px;font-weight:700;\n  transform-origin:0 0;white-space:nowrap}\n#pointer{position:absolute;top:-12px;left:50%;transform:translateX(-50%);z-index:2;\n  width:0;height:0;border-left:11px solid transparent;border-right:11px solid transparent;\n  border-top:20px solid var(--acc);filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}\n#rresult{margin-top:14px;font-size:15px;font-weight:700;min-height:22px;text-align:center}\n#rbet{width:100%;padding:12px;border-radius:12px;border:1px solid var(--line);\n  background:var(--card2);color:var(--text);font-size:17px;text-align:center;outline:none}\n.chips{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;justify-content:center}\n.chips button{padding:7px 12px;border-radius:16px;border:1px solid var(--line);\n  background:var(--card2);color:var(--text);font-size:13px;cursor:pointer}\n.chips button.on{background:var(--grad);color:#1a1205;font-weight:700;border-color:transparent}\n/* КЕЙС */\n#caseAnim{height:110px;display:flex;align-items:center;justify-content:center;font-size:52px}\n#caseAnim.spin{animation:shk .12s infinite}\n@keyframes shk{0%{transform:translateX(-3px)}50%{transform:translateX(3px)}100%{transform:translateX(-3px)}}\n#caseRes{font-size:18px;font-weight:800;text-align:center;min-height:26px;color:var(--acc)}\n/* ГЕРОИ */\n.charit{display:flex;gap:10px;align-items:center;background:var(--card2);\n  border:1px solid var(--line);border-radius:14px;padding:10px;margin-bottom:8px}\n.charit img{width:52px;height:52px;border-radius:10px;object-fit:cover;background:#222}\n.charit .nm{font-weight:600;font-size:14px}\n.charit .rr{font-size:12px;font-weight:700}\n/* ТОП */\n.toprow{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}\n.toprow:last-child{border-bottom:none}\n.toprow .pos{width:26px;height:26px;border-radius:50%;background:var(--card2);\n  display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}\n.toprow .pos.gold{background:var(--acc);color:#1a1205}\n.toprow .pos.silver{background:#c0c8d4;color:#1a1205}\n.toprow .pos.bronze{background:#cd8f52;color:#1a1205}\n.toprow .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}\n.toprow .vl{color:var(--acc);font-weight:700;font-size:13px;white-space:nowrap}\n.inp{width:100%;padding:12px;border-radius:12px;border:1px solid var(--line);\n  background:var(--card2);color:var(--text);font-size:15px;outline:none;margin-bottom:8px}\n.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(20px);\n  background:var(--card2);border:1px solid var(--line);color:var(--text);\n  padding:11px 18px;border-radius:12px;font-size:14px;opacity:0;pointer-events:none;\n  transition:all .25s;z-index:50;max-width:90vw;text-align:center}\n.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}\n.toast.bad{border-color:var(--bad)}\n.bagrow{display:flex;justify-content:space-between;font-size:14px;padding:5px 0}\n.bagrow .z{color:var(--mut)}\n.fadein{animation:fi .25s ease}\n@keyframes fi{from{opacity:0;transform:translateY(6px)}to{opacity:1}}\n</style>\n</head>\n<body>\n\n<div id="login">\n  <div class="logo">⛏️</div>\n  <h1>Шахта — панель</h1>\n  <p>Возьми код у бота командой <b>/код</b> и войди</p>\n  <input id="codeInput" placeholder="000000" inputmode="numeric" maxlength="6">\n  <button onclick="doLogin()">Войти в панель</button>\n  <div class="err" id="loginErr"></div>\n</div>\n\n<div id="app">\n  <header>\n    <div class="hrow">\n      <div>\n        <div class="huser" id="hUser">—</div>\n        <div class="hlvl" id="hLvl">—</div>\n      </div>\n      <div style="text-align:right">\n        <div class="hbal" id="hBal">0</div>\n        <div class="hpick" id="hPick">—</div>\n      </div>\n    </div>\n    <div class="xpbar"><div id="xpFill" style="width:0%"></div></div>\n  </header>\n  <nav id="tabs"></nav>\n  <main id="view"></main>\n</div>\n\n<div class="toast" id="toast"></div>\n\n<script>\nconst TOK_KEY = "mine_tok";\nlet tok = localStorage.getItem(TOK_KEY) || "";\nlet S = null, tab = "mine", mineTimer = null, spinning = false;\n\nfunction esc(s){return (""+(s??"")).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]))}\nfunction fmt(n){return (+n||0).toLocaleString("ru-RU")}\nfunction toast(msg,bad){\n  const t=document.getElementById("toast");\n  t.textContent=msg;t.className="toast show"+(bad?" bad":"");\n  clearTimeout(t._tm);t._tm=setTimeout(()=>t.className="toast",2600);\n}\nasync function api(path,body){\n  const r=await fetch("/api/"+path,{method:"POST",\n    headers:{"Content-Type":"application/json",Authorization:"Bearer "+tok},\n    body:body?JSON.stringify(body):"{}"});\n  if(r.status===401){logout();return {ok:false,error:"Сессия истекла"};}\n  return r.json();\n}\nfunction logout(){localStorage.removeItem(TOK_KEY);tok="";location.reload();}\n\n/* ---------- ВХОД ---------- */\nasync function doLogin(){\n  const code=document.getElementById("codeInput").value.trim();\n  const err=document.getElementById("loginErr");\n  if(!code){err.textContent="Введи код из бота";return;}\n  const r=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},\n    body:JSON.stringify({code})});\n  const j=await r.json();\n  if(j.ok){localStorage.setItem(TOK_KEY,j.token);tok=j.token;boot();}\n  else err.textContent=j.error||"Не удалось войти";\n}\ndocument.getElementById("codeInput").addEventListener("keydown",e=>{if(e.key==="Enter")doLogin();});\n\n/* ---------- СТАРТ ---------- */\nasync function boot(){\n  con
st s=await api("state");\n  if(!s.ok){tok="";localStorage.removeItem(TOK_KEY);return;}\n  S=s;\n  document.getElementById("login").style.display="none";\n  document.getElementById("app").style.display="block";\n  buildTabs();renderHeader();showTab(tab);\n  scheduleMineTimer();\n}\nasync function refresh(){\n  const s=await api("state");\n  if(!s.ok)return;\n  S=s;renderHeader();\n  const old=document.getElementById("mineTime");\n  if(old)document.getElementById("mineBtn").disabled=!s.mine_ready;\n  scheduleMineTimer();\n  const btn=document.getElementById("rBtn");\n  if(btn&&!spinning){btn.disabled=s.roulette_wait>0;btn.textContent=s.roulette_wait>0?("Подожди "+s.roulette_wait+" сек"):"Крутить!";}\n}\n\n/* ---------- ШАПКА ---------- */\nfunction renderHeader(){\n  document.getElementById("hUser").textContent=S.username||"Шахтёр";\n  document.getElementById("hLvl").textContent="Уровень "+S.level;\n  document.getElementById("hBal").textContent=fmt(S.balance)+" 🪙";\n  document.getElementById("hPick").textContent=S.pickaxe;\n  const pct=Math.min(100,Math.round(S.xp/S.xp_needed*100));\n  document.getElementById("xpFill").style.width=pct+"%";\n}\n\n/* ---------- ВКЛАДКИ ---------- */\nconst TABS=[["mine","⛏️ Шахта"],["shop","🛒 Магазин"],["roulette","🎲 Рулетка"],["case","🎁 Кейс"],\n  ["quests","📋 Задания"],["chars","🧙 Герои"],["top","🏆 Топ"],["profile","👤 Профиль"]];\nfunction buildTabs(){\n  document.getElementById("tabs").innerHTML=TABS.map(t=>\n    `<button data-t="${t[0]}" class="${t[0]===tab?"on":""}" onclick="showTab(\'${t[0]}\')">${t[1]}</button>`).join("");\n}\nfunction showTab(t){\n  tab=t;\n  document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on",b.dataset.t===t));\n  const v=document.getElementById("view");\n  v.className="";v.innerHTML=({mine:tabMine,shop:tabShop,roulette:tabRoulette,case:tabCase,\n    quests:tabQuests,chars:tabChars,top:tabTop,profile:tabProfile})[t]();\n  v.classList.add("fadein");\n}\n\n/* ---------- ШАХТА ---------- */\nfunction tabMine(){\n  const loc=S.locations.find(l=>l.current)||S.locations[0];\n  return `\n  <div class="card">\n    <h3>${esc(loc.name)} <span class="muted">×${loc.mult}</span></h3>\n    <button class="btn" id="mineBtn" onclick="doMine()" ${S.mine_ready?"":"disabled"}>\n      ${S.mine_ready?"⛏️ Накопать!":"⏳ Подожди "+S.mine_wait+" сек."}</button>\n    <div id="mineRes"></div>\n  </div>\n  <div class="card">\n    <h3>🎒 Рюкзак <span class="muted">(${fmt(S.bag_value)} 🪙)</span></h3>\n    ${S.backpack.map(b=>`<div class="bagrow"><span>${b.name} <span class="z">×${b.count}</span></span><span class="muted">${fmt(b.count*b.price)} 🪙</span></div>`).join("")}\n    <button class="btn" onclick="doSell()">💰 Продать всё</button>\n  </div>\n  <div class="card">\n    <h3>🎁 Бонус</h3>\n    <div class="muted">${S.bonus_ready?"Бонус доступен!":"Следующий через "+S.bonus_left}</div>\n    <button class="btn blue" onclick="doBonus()" ${S.bonus_ready?"":"disabled"}>Забрать бонус</button>\n  </div>`;\n}\nasync function doMine(){\n  const r=await api("mine");\n  if(!r.ok){toast(r.error,true);refresh();return;}\n  const box=document.getElementById("mineRes");\n  box.innerHTML=r.got.map(g=>`<div class="bagrow"><span>${g.name}</span><span>+${g.count}</span></div>`).join("")\n    +`<div class="bagrow"><span class="muted">Опыт</span><span class="muted">+${r.xp} XP</span></div>`;\n  if(r.levelup>0)toast("🎉 Новый уровень: "+r.level+"!");\n  refresh();\n}\nasync function doSell(){\n  const r=await api("sell");\n  if(!r.ok){toast(r.error,true);return;}\n  toast("💰 Продано на "+fmt(r.total)+" монет!");\n  refresh();\n}\nasync function doBonus(){\n  const r=await api("bonus");\n  if(!r.ok){toast(r.error,true);refresh();return;}\n  toast("🎁 +"+fmt(r.amount)+" монет!");\n  refresh();\n}\nfunction scheduleMineTimer(){\n  clearInterval(mineTimer);\n  mineTimer=setInterval(async()=>{\n    const btn=document.getElementById("mineBtn");\n    if(!btn)return;\n    if(S.mine_wait>0){S.mine_wait--;\n      btn.textContent="⏳ Подожди "+S.mine_wait+" сек.";\n      if(S.mine_wait===0)refresh();\n    }\n  },1000);\n}\n\n/* ---------- МАГАЗИН ---------- */\nfunction tabShop(){\n  return `\n  <div class="card">\n    <h3>🏪 Локации</h3>\n    ${S.locations.map(l=>`\n      <div class="locit ${l.current?"cur":""} ${l.available?"":"lock"}" onclick="${l.available&&!l.current?`pickLoc(\'${l.key}\')`:""}">\n        <img src="${l.img}" onerror="this.style.display=\'none\'">\n        <div><div class="nm">${l.name}</div><div class="mt">×${l.mult} добыча</div>\n        <div class="muted">${l.current?"Сейчас ты здесь":(l.available?"Нажми, чтобы перейти":"Нужен уровень "+l.min_level)}</div></div>\n      </div>`).join("")}\n  </div>\n  <div class="card">\n    <h3>🛒 Кирки ${S.discount>0?`<span class="muted">скидка ${S.discount}%</span>`:""}</h3>\n    <div class="grid">\n      ${S.shop.map(p=>{\n        const price=Math.max(1,Math.round(p.price*(100-S.discount)/100));\n        const owned=S.level>=p.level&&p.price>0;\n        return `<div class="shopit ${owned?"own":""}">\n          <div class="nm">${p.name}</div>\n          <div class="pw">Сила +${p.power}</div>\n          <div class="pr">Уровень ${p.level}</div>\n          <div class="pr">${p.price>0?fmt(price)+" 🪙":"—"}</div>\n          <button class="btn ${owned?"ghost":""}" style="padding:9px;font-size:13px"\n            onclick="doBuy(\'${p.key}\')" ${p.price>0&&S.level>=p.level?"":"disabled"}>\n            ${owned?"✓ Доступна":(p.price>0?"Купить":"Стартовая")}</button>\n        </div>`;}).join("")}\n    </div>\n  </div>\n  <div class="card">\n    <h3>⚙️ Автосбор — уровень ${S.auto_level}</h3>\n    <div class="muted">${S.auto_level>0?("Шахта работает сама, интервал "+S.auto_mins_left+" мин до следующего сбора"):"Шахта добывает руду без тебя каждые 3 часа"}</div>\n    ${S.auto_next_price?`<button class="btn blue" onclick="doAuto()">Улучшить за ${fmt(S.auto_next_price)} 🪙</button>`:`<div class="muted">Максимум прокачан ✅</div>`}\n  </div>`;\n}\nasync function pickLoc(k){const r=await api("location",{key:k});toast(r.ok?("Локация: "+r.location):(r.error),!r.ok);if(r.ok)refresh();}\nasync function doBuy(k){const r=await api("buy",{pickaxe:k});toast(r.ok?(r.pickaxe+" куплена за "+fmt(r.price)+" 🪙"):(r.error),!r.ok);if(r.ok)refresh();}\nasync function doAuto(){const r=await api("auto");toast(r.ok?("Автосбор — уровень "+r.level):r.error,!r.ok);if(r.ok)refresh();}\n\n/* ---------- РУЛЕТКА ---------- */\nconst SEC_COLORS=["#ffd54a","#ff9f43","#6c5ce7","#2ecc71","#e74c3c"];\nconst SEC_NAMES=["x5 💥","x3 🔥","x2 ✅","x1 ➖","❌"];\nlet wheelDeg=0;\nfunction tabRoulette(){\n  if(!S.roulette_open){\n    return `<div class="card" style="text-align:center;padding:30px 14px">\n      <div style="font-size:44px">🔒</div>\n      <h3 style="margin-top:10px">Рулетка с ${S.roulette_min_level} уровня</h3>\n      <div class="muted">Прокачай уровень в шахте, чтобы открыть игру на монеты</div></div>`;\n  }\n  return `\n  <div class="card">\n    <h3 style="text-align:center">🎲 Рулетка удачи</h3>\n    <div class="wheelbox">\n      <div class="wheelwrap">\n        <div id="pointer"></div>\n        <div id="wheel"></div>\n      </div>\n      <div id="rresult">&nbsp;</div>\n    </div>\n    <input id="rbet" type="number" min="${10}" max="${100000}" step="10" placeholder="Ставка (10 — 100 000)">\n    <div class="chips">\n      ${[100,1000,5000,10000].map(v=>`<button onclick="addBet(${v})">+${fmt(v)}</button>`).join("")}\n    </div>\n    <button class="btn" id="rBtn" onclick="doSpin()" ${S.roulette_wait>0?"disabled":""}>\n      ${S.roulette_wait>0?"Подожди "+S.roulette_wait+" сек":"Крутить!"}</button>\n  </div>`;\n}\nfunction drawWheel(){\n  const w=document.getElementById("wheel");\n  if(!w||w.dataset.drawn)return;\n  const n=5,seg=360/n;\n  const stops=[];w.dataset.drawn="1";\n  for(let i=0;i<n;i++)stops.push(`${SEC_COLORS[i]} ${i*seg}deg ${(i+1)*seg}deg`);\n  w.style.background=`conic-gradient(${stops.join(",")})`;\n  w.style.transform="rotate(0deg)";\n  for(let i=0;i<n;i++){\n    const s=document.createElement("div");\n    s.className="wlab";s.textContent=SEC_NAMES[i];\n    s.style.transform=`rotate(${i*seg+seg/2}deg) translate(0,-96px) translate(-50%,-50%)`;\n    s.style.color="#10131a";\n    w.appendChild(s);\n  }\n}\nfunction addBet(v){const el=document.getElementById("rbet");el.value=(+el.value||0)+v;}\nasync function doSpin(){\n  if(spinning)return;\n  const betEl=document.getElementById("rbet");\n  const bet=+betEl.value;\n  if(!bet){toast("Введи ставку",true);return;}\n  spinning=true;\n  const btn=document.getElementById("rBtn");btn.disabled=true;btn.textContent="Крутится...";\n  document.getElementById("rresult").innerHTML="&nbsp;";\n  const r=await api("roulette",{bet});\n  if(!r.ok){toast(r.error,true);spinning=false;refresh();return;}\n  const w=document.getElementById("wheel");\n  drawWheel();\n  const seg=360/5;\n  wheelDeg=wheelDeg+360*4+((360-(r.idx*seg+seg/2))-(wheelDeg%360)+360)%360;\n  w.style.transform=`rotate(${wheelDeg}deg)`;\n  setTimeout(()=>{\n    const res=document.getElementById("rresult");\n    if(r.jackpot)res.style.color="#ffd54a";\n    else if(r.delta>0)res.style.color="#2ecc71";\n    else if(r.delta===0)res.style.color="#8b96a8";\n    else res.style.color="#ff5c5c";\n    res.textContent=`${r.sector} — ${r.delta>0?"+"+fmt(r.delta):(r.delta===0?"возврат ставки":fmt(r.delta))} 🪙`;\n    spinning=false;refresh();\n  },4300);\n}\n\n/* ---------- КЕЙС ---------- */\nfunction tabCase(){\n  return `\n  <div class="card" style="text-align:center">\n    <h3>🎁 Бесплатный кейс</h3>\n    <div id="caseAnim">🎁</div>\n    <div id="caseRes"></div>\n    ${S.case_ready?"":`<div class="muted">Следующий кейс через ${S.case_left}</div>`}\n    <button class="btn" id="caseBtn" onclick="doCase()" ${S.case_ready?"":"disabled"}>\n      ${S.case_ready?"Открыть кейс":"🔒 Закрыт"}</button>\n  </div>\n  <div class="card"><h3>Что внутри</h3>\n    ${[["🪙 100 монет"
,"30%"],["🪙 500 монет","25%"],["🪙 1 000 монет","20%"],["🪙 2 500 монет","12%"],\n       ["🪙 5 000 монет","8%"],["🪙 10 000 монет","3.5%"],["💥 ДЖЕКПОТ 50 000 монет","1.5%"]]\n      .map(x=>`<div class="bagrow"><span>${x[0]}</span><span class="muted">${x[1]}</span></div>`).join("")}\n  </div>`;\n}\nasync function doCase(){\n  const anim=document.getElementById("caseAnim");\n  const btn=document.getElementById("caseBtn");\n  btn.disabled=true;anim.classList.add("spin");\n  const r=await api("case");\n  anim.classList.remove("spin");\n  if(!r.ok){toast(r.error,true);refresh();return;}\n  anim.textContent=r.jackpot?"💥":"🎉";\n  document.getElementById("caseRes").textContent=r.label;\n  toast(r.label);\n  refresh();\n}\n\n/* ---------- ЗАДАНИЯ ---------- */\nfunction tabQuests(){\n  return `\n  <div class="card">\n    <h3>📋 Ежедневные задания</h3>\n    ${S.quests.items.map(q=>{\n      const done=q.done>=q.target;\n      return `<div class="bagrow"><span>${q.title}</span>\n        <span class="${done?"":"muted"}" style="color:${done?"var(--ok)":""}">${Math.min(q.done,q.target)}/${q.target}</span></div>\n        <div class="xpbar" style="margin:2px 0 8px"><div style="width:${Math.min(100,q.done/q.target*100)}%"></div></div>`;}).join("")}\n    <div class="muted">Награда за все: ${fmt(S.quests.reward)} 🪙</div>\n    <button class="btn" onclick="doClaim()" ${S.quests.claimed?"disabled":""}>\n      ${S.quests.claimed?"✓ Награда получена":"Забрать награду"}</button>\n  </div>`;\n}\nasync function doClaim(){const r=await api("claim");toast(r.ok?("🎉 +"+fmt(r.reward)+" монет"):r.error,!r.ok);if(r.ok)refresh();}\n\n/* ---------- ГЕРОИ ---------- */\nfunction tabChars(){\n  if(!S.characters.length){\n    return `<div class="card" style="text-align:center;padding:30px 14px">\n      <div style="font-size:44px">🧙</div>\n      <h3 style="margin-top:10px">Пока никого</h3>\n      <div class="muted">Копай в шахте — персонажи встречаются во время добычи (шанс ~3%)</div></div>`;\n  }\n  return `\n  <div class="card">\n    <h3>🧙 Отряд <span class="muted">+${S.char_bonus}% к добыче</span></h3>\n    ${S.characters.map(c=>`\n      <div class="charit">\n        <img src="${c.img||""}" onerror="this.style.display=\'none\'">\n        <div><div class="nm">${esc(c.name)}</div>\n        <div class="rr" style="color:${c.color}">${esc(c.rarity)}</div>\n        <div class="muted">+${c.bonus_pct}% к добыче</div></div>\n      </div>`).join("")}\n  </div>`;\n}\n\n/* ---------- ТОП ---------- */\nfunction medal(i){return i===0?"gold":i===1?"silver":i===2?"bronze":"";}\nfunction tabTop(){\n  return `\n  <div class="card"><h3>🪙 Богатейшие</h3>\n    ${S.top_rich.map((u,i)=>`<div class="toprow"><div class="pos ${medal(i)}">${i+1}</div>\n      <div class="nm">${esc(u.username||"Игрок")}</div><div class="vl">${fmt(u.balance)} 🪙 · ур.${u.level}</div></div>`).join("")||`<div class="muted">Пока пусто</div>`}\n  </div>\n  <div class="card"><h3>⛰️ Уровни</h3>\n    ${S.top_level.map((u,i)=>`<div class="toprow"><div class="pos ${medal(i)}">${i+1}</div>\n      <div class="nm">${esc(u.username||"")}</div><div class="vl">ур.${u.level}</div></div>`).join("")||`<div class="muted">Пока пусто</div>`}\n  </div>`;\n}\n\n/* ---------- ПРОФИЛЬ ---------- */\nfunction tabProfile(){\n  return `\n  <div class="card">\n    <h3>🎟️ Промокод</h3>\n    <input class="inp" id="promoInp" placeholder="Введи промокод">\n    <button class="btn blue" onclick="doPromo()">Активировать</button>\n  </div>\n  <div class="card">\n    <h3>💸 Перевод монет</h3>\n    <div class="muted">Минимум 100 монет. Ник или ID получателя.</div>\n    <input class="inp" id="trTo" placeholder="Ник получателя" style="margin-top:8px">\n    <input class="inp" id="trAmt" type="number" min="100" placeholder="Сумма">\n    <button class="btn" onclick="doTransfer()">Перевести</button>\n  </div>\n  <div class="card">\n    <h3>ℹ️ Информация</h3>\n    <div class="bagrow"><span class="muted">Ник</span><span>${esc(S.username)}</span></div>\n    <div class="bagrow"><span class="muted">Уровень</span><span>${S.level}</span></div>\n    <div class="bagrow"><span class="muted">Кирка</span><span>${S.pickaxe}</span></div>\n    <div class="bagrow"><span class="muted">Локация</span><span>${esc(S.location)}</span></div>\n    <div class="bagrow"><span class="muted">Скидка на покупки</span><span>${S.discount}%</span></div>\n    <button class="btn ghost" onclick="logout()">Выйти</button>\n  </div>`;\n}\nasync function doPromo(){\n  const code=document.getElementById("promoInp").value.trim();\n  if(!code){toast("Введи промокод",true);return;}\n  const r=await api("promo",{code});\n  toast(r.ok?("✅ "+r.text):r.error,!r.ok);\n  if(r.ok)refresh();\n}\nasync function doTransfer(){\n  const t=document.getElementById("trTo").value.trim();\n  const a=+document.getElementById("trAmt").value;\n  const r=await api("transfer",{target:t,amount:a});\n  toast(r.ok?("💸 Отправлено "+fmt(r.amount)+" 🪙 игроку "+r.to):r.error,!r.ok);\n  if(r.ok
){refresh();showTab("profile");}\n}\n\n/* ---------- АВТОВХОД TELEGRAM ---------- */\nwindow.addEventListener("load",async()=>{\n  const tg=window.Telegram&&window.Telegram.WebApp;\n  if(tg&&tg.initData&&tg.initData.length>10){\n    const r=await fetch("/api/tg_auth",{method:"POST",headers:{"Content-Type":"application/json"},\n      body:JSON.stringify({initData:tg.initData})});\n    const j=await r.json();\n    if(j.ok){localStorage.setItem(TOK_KEY,j.token);tok=j.token;tg.expand();}\n  }\n  if(tok)boot();\n});\n</script>\n</body>\n</html>\n'
)


# ================= СТРАНИЦА И ЗАПУСК =================

def index(request):
    return web.Response(text=HTML_PAGE, content_type="text/html")


API_POST = [
    ("login", api_login),
    ("tg_auth", api_tg_auth),
    ("state", api_state),
    ("mine", api_mine),
    ("sell", api_sell),
    ("bonus", api_bonus),
    ("roulette", api_roulette),
    ("buy", api_buy),
    ("location", api_location),
    ("auto", api_auto),
    ("case", api_case),
    ("transfer", api_transfer),
    ("promo", api_promo),
    ("claim", api_claim),
]


def build_app():
    app = web.Application()
    app.router.add_get("/", index)
    for path, fn in API_POST:
        app.router.add_post("/api/" + path, fn)
    if os.path.isdir(IMAGES_DIR):
        app.router.add_static("/img/", IMAGES_DIR)
    return app


if __name__ == "__main__":
    print("Веб-панель запущена на порту", PORT)
    print("Открой: http://localhost:" + str(PORT))
    web.run_app(build_app(), host="0.0.0.0", port=PORT, print=None)
