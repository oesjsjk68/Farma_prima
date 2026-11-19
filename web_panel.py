import os
import asyncio
import random
import sqlite3
import secrets
import hashlib
import hmac
import json
from urllib.parse import parse_qsl
from datetime import datetime, timedelta

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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(SCRIPT_DIR, "data", "bot_db.sqlite")
if not os.path.exists(DB_NAME):
    alt = os.path.join(SCRIPT_DIR, "bot_db.sqlite")
    if os.path.exists(alt):
        DB_NAME = alt

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

LOCATIONS = [
    {"key": "mine_1", "name": "⛏️ Старая шахта",       "mult": 1.0, "min_level": 1},
    {"key": "mine_2", "name": "🗻 Глубокие штольни",   "mult": 1.5, "min_level": 15},
    {"key": "mine_3", "name": "🌋 Огненные пещеры",    "mult": 2.0, "min_level": 30},
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
    "stone": "камня", "iron": "железной руды",
    "copper": "медной руды", "gold": "золотой руды",
}

tokens = {}          # token -> user_id
roulette_cd = {}     # token -> last spin ts


def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    return conn


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
    cur.execute("SELECT ore_key, price FROM prices")
    result = dict(cur.fetchall())
    conn.close()
    return result


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


def can_mine(user):
    if not user.get("last_mine_at"):
        return True
    last = datetime.fromisoformat(user["last_mine_at"])
    return datetime.now() >= last + timedelta(seconds=3)


def mine_seconds_left(user):
    last = datetime.fromisoformat(user["last_mine_at"])
    end = last + timedelta(seconds=3)
    return max(0, int((end - datetime.now()).total_seconds()))


def can_bonus(user):
    if not user.get("last_bonus_at"):
        return True
    last = datetime.fromisoformat(user["last_bonus_at"])
    return datetime.now() >= last + timedelta(hours=12)


def bonus_time_left(user):
    last = datetime.fromisoformat(user["last_bonus_at"])
    end = last + timedelta(hours=12)
    total_min = max(0, int((end - datetime.now()).total_seconds() // 60))
    return total_min // 60, total_min % 60


def add_xp(user_id, user, gained):
    new_xp = user["xp"] + gained
    new_level = user["level"]
    levelups = 0
    while new_xp >= xp_needed_for_next_level(new_level):
        new_xp -= xp_needed_for_next_level(new_level)
        new_level += 1
        levelups += 1
    update_user(user_id, xp=new_xp, level=new_level)
    return new_level, levelups


def auth_user(request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = tokens.get(token)
    if not user_id:
        return None, None
    return get_user(user_id), token


def api_json(data, status=200):
    return web.json_response(data, status=status)


# ================= АВТОВХОД ЧЕРЕЗ TELEGRAM MINI APP =================

def verify_init_data(init_data: str):
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


# ================= API =================

async def api_login(request):
    data = await request.json()
    code = str(data.get("code", "")).strip()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, created_at FROM web_codes WHERE code = ?", (code,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    if not row:
        return api_json({"ok": False, "error": "Код не найден. Попроси у бота новый: /код"}, 401)
    user_id, created = row
    if datetime.now() - datetime.fromisoformat(created) > timedelta(minutes=15):
        return api_json({"ok": False, "error": "Код устарел. Попроси новый: /код"}, 401)
    conn = get_conn()
    conn.execute("DELETE FROM web_codes WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    token = secrets.token_hex(16)
    tokens[token] = user_id
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


async def api_state(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    prices = get_prices()
    backpack = [{"key": k, "name": ORES[k]["name"], "count": user.get(f"ore_{k}", 0),
                 "price": prices.get(k, ORES[k]["price"])} for k in ORE_KEYS]
    total_bag = sum(x["count"] * x["price"] for x in backpack)
    needed = xp_needed_for_next_level(user["level"])
    pick = PICKAXE_BY_KEY.get(user.get("pickaxe_key", "wood"), PICKAXES[0])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, balance, level FROM users ORDER BY balance DESC, level DESC LIMIT 10")
    top_rich = cur.fetchall()
    cur.execute("SELECT username, level FROM users ORDER BY level DESC, balance DESC LIMIT 10")
    top_level = cur.fetchall()
    conn.close()
    if can_bonus(user):
        bonus_left = "доступен"
    else:
        h, m = bonus_time_left(user)
        bonus_left = f"{h} ч {m} мин"

    # локация
    loc_key = user.get("location_key") or "mine_1"
    cur_loc = next((l for l in LOCATIONS if l["key"] == loc_key), LOCATIONS[0])
    locations = [{"key": l["key"], "name": l["name"], "mult": l["mult"],
                  "min_level": l["min_level"], "current": l["key"] == loc_key,
                  "available": user["level"] >= l["min_level"]} for l in LOCATIONS]

    # автосбор
    auto_lvl = int(user.get("auto_level") or 0)
    mins_left = 0
    if auto_lvl > 0 and user.get("auto_last_at"):
        end = datetime.fromisoformat(user["auto_last_at"]) + timedelta(hours=AUTO_INTERVAL_HOURS)
        mins_left = max(0, int((end - datetime.now()).total_seconds() // 60))
    auto_price = auto_next_price(auto_lvl) if auto_lvl < AUTO_MAX_LEVEL else None

    # персонажи
    chars = get_characters(user["user_id"])
    chars_out = [{"name": c.get("name", "?"), "rarity": c.get("rarity", ""),
                  "bonus_pct": c.get("bonus_pct", 0)} for c in chars]

    return api_json({
        "ok": True,
        "username": user.get("username", ""),
        "balance": user["balance"],
        "xp": user["xp"], "xp_needed": needed, "level": user["level"],
        "pickaxe": pick["name"],
        "backpack": backpack, "bag_value": total_bag,
        "mine_ready": can_mine(user), "mine_wait": mine_seconds_left(user),
        "bonus_ready": can_bonus(user), "bonus_left": bonus_left,
        "shop": PICKAXES,
        "top_rich": top_rich, "top_level": top_level,
        "roulette_open": user["level"] >= ROULETTE_MIN_LEVEL,
        "roulette_min_level": ROULETTE_MIN_LEVEL,
        "locations": locations, "location": cur_loc["name"],
        "auto_level": auto_lvl,
        "auto_next_price": auto_price,
        "auto_mins_left": mins_left if auto_lvl > 0 else None,
        "characters": chars_out,
    })


async def api_mine(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    if not can_mine(user):
        return api_json({"ok": False, "error": f"Подожди ещё {mine_seconds_left(user)} сек."}, 429)
    loc_key = user.get("location_key") or "mine_1"
    loc = next((l for l in LOCATIONS if l["key"] == loc_key), LOCATIONS[0])
    mult = loc["mult"]
    pick = PICKAXE_BY_KEY.get(user.get("pickaxe_key", "wood"), PICKAXES[0])
    char_bonus = 0.0
    for c in get_characters(user["user_id"]):
        try:
            char_bonus += float(c.get("bonus_pct") or 0)
        except (TypeError, ValueError):
            pass
    mult = mult * (1.0 + min(0.4, char_bonus) / 100.0)

    stone = int((random.randint(2, 4) + pick["power"] // 10 + user["level"] - 1) * mult)
    iron = int((random.randint(1, 2) if random.random() < 0.2 + pick["power"] / 200 + (user["level"] - 1) / 100 else 0) * mult)
    copper = int((random.randint(1, 2) if random.random() < 0.1 + pick["power"] / 400 + (user["level"] - 1) / 200 else 0) * mult)
    gold = int((1 if random.random() < 0.05 + pick["power"] / 800 + (user["level"] - 1) / 400 else 0) * mult)
    total_xp = (stone * ORES["stone"]["xp"] + iron * ORES["iron"]["xp"]
                + copper * ORES["copper"]["xp"] + gold * ORES["gold"]["xp"])
    update_user(user["user_id"],
                ore_stone=user.get("ore_stone", 0) + stone, ore_iron=user.get("ore_iron", 0) + iron,
                ore_copper=user.get("ore_copper", 0) + copper, ore_gold=user.get("ore_gold", 0) + gold,
                last_mine_at=datetime.now().isoformat())
    new_level, levelups = add_xp(user["user_id"], user, total_xp)
    got = []
    for k, c in zip(ORE_KEYS, [stone, iron, copper, gold]):
        if c > 0:
            got.append({"name": ORES[k]["name"], "count": c})
    return api_json({"ok": True, "got": got, "xp": total_xp,
                     "levelup": levelups, "level": new_level,
                     "location": loc["name"]})


async def api_sell(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    prices = get_prices()
    total = 0
    lines = []
    for k in ORE_KEYS:
        cnt = user.get(f"ore_{k}", 0)
        if cnt > 0:
            money = cnt * prices.get(k, ORES[k]["price"])
            lines.append(f"{ORES[k]['name']} × {cnt} = {money}")
            total += money
    if total == 0:
        return api_json({"ok": False, "error": "Рюкзак пуст!"})
    update_user(user["user_id"], balance=user["balance"] + total,
                ore_stone=0, ore_iron=0, ore_copper=0, ore_gold=0)
    return api_json({"ok": True, "total": total, "lines": lines})


async def api_bonus(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    if not can_bonus(user):
        h, m = bonus_time_left(user)
        return api_json({"ok": False, "error": f"Бонус через {h} ч {m} мин"})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = 'bonus_amount'")
    row = cur.fetchone()
    conn.close()
    amount = int(row[0]) if row else 5000
    update_user(user["user_id"], balance=user["balance"] + amount,
                last_bonus_at=datetime.now().isoformat())
    return api_json({"ok": True, "amount": amount})


async def api_roulette(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    if user["level"] < ROULETTE_MIN_LEVEL:
        return api_json({"ok": False, "error": f"Рулетка с {ROULETTE_MIN_LEVEL} уровня"})
    data = await request.json()
    bet = data.get("bet")
    if bet is None:
        now = datetime.now().timestamp()
        left = roulette_cd.get(token, 0)
        if now - left < ROULETTE_COOLDOWN_SEC:
            return api_json({"ok": False, "error": f"Подожди {int(ROULETTE_COOLDOWN_SEC - (now - left))} сек."})
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
        return api_json({"ok": False, "error": "Крути не чаще раза в 30 сек."})
    roll = random.random()
    cum = 0.0
    sector = ROULETTE_SECTORS[-1]
    for s in ROULETTE_SECTORS:
        cum += s["chance"]
        if roll < cum:
            sector = s
            break
    roulette_cd[token] = now
    win = int(bet * sector["mult"])
    delta = win - bet
    new_balance = user["balance"] + delta
    update_user(user["user_id"], balance=new_balance)
    return api_json({"ok": True, "sector": sector["name"], "bet": bet,
                     "win": win, "delta": delta, "balance": new_balance})


async def api_buy(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    data = await request.json()
    wanted = next((p for p in PICKAXES if p["key"] == data.get("key")), None)
    if not wanted:
        return api_json({"ok": False, "error": "Такой кирки нет"})
    keys = [p["key"] for p in PICKAXES]
    if keys.index(wanted["key"]) != keys.index(user.get("pickaxe_key", "wood")) + 1:
        return api_json({"ok": False, "error": "Покупай по порядку"})
    if user["level"] < wanted["level"]:
        return api_json({"ok": False, "error": f"Нужен уровень {wanted['level']}"})
    if user["balance"] < wanted["price"]:
        return api_json({"ok": False, "error": f"Нужно {wanted['price']}, у тебя {user['balance']}"})
    update_user(user["user_id"], balance=user["balance"] - wanted["price"],
                pickaxe_key=wanted["key"])
    return api_json({"ok": True, "msg": f"Куплена кирка: {wanted['name']}!"})


async def api_location(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    data = await request.json()
    loc = next((l for l in LOCATIONS if l["key"] == data.get("key")), None)
    if not loc:
        return api_json({"ok": False, "error": "Такой локации нет"})
    if user["level"] < loc["min_level"]:
        return api_json({"ok": False, "error": f"Нужен уровень {loc['min_level']}"})
    update_user(user["user_id"], location_key=loc["key"])
    return api_json({"ok": True, "msg": f"Локация: {loc['name']} (×{loc['mult']})"})


async def api_auto_upgrade(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    lvl = int(user.get("auto_level") or 0)
    if lvl >= AUTO_MAX_LEVEL:
        return api_json({"ok": False, "error": "Максимальный уровень автосбора"})
    price = auto_next_price(lvl)
    if user["balance"] < price:
        return api_json({"ok": False, "error": f"Не хватает монет: нужно {price}, у тебя {user['balance']}"})
    kwargs = {"balance": user["balance"] - price, "auto_level": lvl + 1}
    if lvl == 0:
        kwargs["auto_last_at"] = datetime.now().isoformat()
    update_user(user["user_id"], **kwargs)
    return api_json({"ok": True, "msg": f"Автосбор прокачан до уровня {lvl + 1}! Сбор каждые {AUTO_INTERVAL_HOURS} часа."})


async def api_promo(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    data = await request.json()
    code = str(data.get("code", "")).strip().upper()
    if not code:
        return api_json({"ok": False, "error": "Введи промокод"})
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT amount, uses, type FROM promos WHERE code = ?", (code,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    if not row:
        conn.close()
        return api_json({"ok": False, "error": "Промокод не найден"})
    try:
        cur.execute("SELECT 1 FROM promo_users WHERE user_id = ? AND code = ?", (user["user_id"], code))
        already = cur.fetchone()
    except sqlite3.OperationalError:
        already = None
    if already:
        conn.close()
        return api_json({"ok": False, "error": "Ты уже активировал этот промокод"})
    amount, uses, ptype = row
    ptype = ptype or "money"
    if uses <= 0:
        conn.close()
        return api_json({"ok": False, "error": "Промокод уже исчерпан"})
    cur.execute("UPDATE promos SET uses = uses - 1 WHERE code = ?", (code,))
    try:
        cur.execute("INSERT INTO promo_users (user_id, code) VALUES (?, ?)", (user["user_id"], code))
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    if ptype == "money":
        update_user(user["user_id"], balance=user["balance"] + amount)
    elif ptype == "xp":
        add_xp(user["user_id"], user, amount)
    elif ptype in ORE_KEYS:
        col = f"ore_{ptype}"
        update_user(user["user_id"], **{col: user.get(col, 0) + amount})
    else:
        update_user(user["user_id"], balance=user["balance"] + amount)
    return api_json({"ok": True, "msg": f"Активирован: +{amount} {PROMO_TYPES.get(ptype, ptype)}"})


# ================= HTML =================

PAGE = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Шахта</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#111417;--card:#1c2126;--card2:#242a31;--acc:#d6f94a;--tx:#eef2f5;--mut:#8b949c}
*{box-sizing:border-box;margin:0;font-family:sans-serif}
body{background:var(--bg);color:var(--tx);max-width:480px;margin:0 auto;min-height:100vh;display:flex;flex-direction:column}
header{padding:14px 16px;display:flex;justify-content:space-between;align-items:center;gap:8px}
.logo{font-weight:800;font-size:22px;letter-spacing:-.5px}
.chip{background:var(--card);border-radius:14px;padding:8px 12px;font-weight:700;display:flex;gap:6px;align-items:center}
main{flex:1;padding:0 16px 90px}
.center{display:flex;flex-direction:column;align-items:center;gap:14px;padding-top:26px}
#mineBtn{width:190px;height:190px;border-radius:50%;border:none;font-size:22px;font-weight:800;
 background:var(--acc);color:#111;box-shadow:0 0 40px #d6f94a44;cursor:pointer;transition:transform .08s}
#mineBtn:active{transform:scale(.93)}
#mineBtn:disabled{opacity:.4;box-shadow:none;cursor:default}
.bar{width:100%;height:8px;background:var(--card2);border-radius:6px;overflow:hidden}
.bar>div{height:100%;background:var(--acc);width:0%}
nav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:480px;
 background:var(--card);display:flex;overflow-x:auto;border-radius:18px 18px 0 0}
nav button{flex:1;background:none;border:none;color:var(--mut);padding:12px 0 14px;font-size:18px;cursor:pointer;min-width:56px}
nav button.on{color:var(--acc)}
.screen{display:none}
.screen.on{display:block}
.card{background:var(--card);border-radius:16px;padding:14px;margin-bottom:12px}
.row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #ffffff12}
.row:last-child{border:none}
button.act{background:var(--acc);border:none;color:#111;font-weight:700;border-radius:12px;padding:10px 16px;cursor:pointer}
button.ghost{background:var(--card2);color:var(--tx);border:none;border-radius:12px;padding:10px 16px;cursor:pointer}
input{background:var(--card2);border:none;color:var(--tx);border-radius:12px;padding:10px 12px;width:100%}
h3{margin:14px 0 8px;font-size:15px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}
#toast{position:fixed;left:50%;bottom:84px;transform:translateX(-50%);background:var(--card2);
 border-radius:12px;padding:12px 18px;display:none;max-width:90%;text-align:center;z-index:9}
.mut{color:var(--mut);font-size:13px}
</style></head><body>
<header><div class="logo">prime</div><div class="chip" id="bal">💰 0</div><div class="chip" id="lvl">🏅 1</div></header>
<main>
<div id="login" class="center" style="padding-top:80px">
 <div style="font-size:40px">⛏️</div>
 <h2>Вход в шахту</h2>
 <p class="mut">Открой через кнопку бота — вход автоматический.<br>Или напиши боту <b>/код</b> и введи код здесь</p>
 <input id="code" placeholder="Код из бота (если открыл в браузере)" style="text-align:center">
 <button class="act" onclick="login()">Войти</button>
</div>
<div id="app" style="display:none">
 <div class="screen on" id="s-home">
  <div class="center">
   <div class="bar" style="max-width:280px"><div id="xpbar"></div></div>
   <div class="mut" id="xptext"></div>
   <button id="mineBtn" onclick="mine()">⛏️<br>Копать</button>
   <div class="mut" id="minewait"></div>
   <div class="mut" id="locinfo"></div>
  </div>
 </div>
 <div class="screen" id="s-bag">
  <h3>🎒 Инвентарь</h3>
  <div class="card" id="bagList"></div>
  <button class="act" style="width:100%" onclick="sell()">💰 Продать всё</button>
 </div>
 <div class="screen" id="s-mines"><h3>🗺 Шахты</h3><div id="locList"></div></div>
 <div class="screen" id="s-shop"><h3>🛒 Магазин кирок</h3><div id="shopList"></div></div>
 <div class="screen" id="s-auto">
  <h3>🤖 Автосбор</h3>
  <div class="card" id="autoCard"></div>
  <button class="act" style="width:100%" id="autoBtn" onclick="autoUp()">Улучшить автосбор</button>
 </div>
 <div class="screen" id="s-top">
  <h3>🏆 Богачи</h3><div class="card" id="topRich"></div>
  <h3>🏆 Уровни</h3><div class="card" id="topLvl"></div>
 </div>
 <div class="screen" id="s-prof">
  <div class="card" id="profCard"></div>
  <div class="card"><div class="row"><span>🗺 Локация</span><b id="profLoc"></b></div><div class="row"><span>🤖 Автосбор</span><b id="profAuto"></b></div></div>
  <h3>🧙 Персонажи</h3><div class="card" id="charList"></div>
  <h3>🎁 Бонус</h3>
  <div class="card"><button class="act" style="width:100%" id="bonusBtn" onclick="bonus()">Забрать бонус</button></div>
  <h3>🎟 Промокод</h3>
  <div class="card">
   <input id="promoCode" placeholder="Промокод" style="text-align:center">
   <button class="act" style="width:100%;margin-top:8px" onclick="promo()">Активировать</button>
  </div>
  <h3>🎲 Рулетка</h3>
  <div class="card">
   <div id="roulInfo" class="mut"></div>
   <input id="bet" placeholder="Ставка, напр. 100" style="margin-top:8px;text-align:center">
   <button class="act" style="width:100%;margin-top:8px" onclick="spin()">Крутить</button>
  </div>
 </div>
</div>
</main>
<nav id="nav" style="display:none">
 <button class="on" onclick="tab(0,this)">⛏️<br><small>Добыча</small></button>
 <button onclick="tab(1,this)">🎒<br><small>Рюкзак</small></button>
 <button onclick="tab(2,this)">🗺<br><small>Шахты</small></button>
 <button onclick="tab(3,this)">🛒<br><small>Магазин</small></button>
 <button onclick="tab(4,this)">🤖<br><small>Авто</small></button>
 <button onclick="tab(5,this)">🏆<br><small>Топ</small></button>
 <button onclick="tab(6,this)">👤<br><small>Профиль</small></button>
</nav>
<div id="toast"></div>
<script>
const S={t:localStorage.token||""};
const $=id=>document.getElementById(id);
function toast(m,ok=true){const t=$("toast");t.textContent=m;t.style.display="block";
 t.style.color=ok?"var(--acc)":"#ff7a7a";setTimeout(()=>t.style.display="none",2500);}
async function api(path,body){const r=await fetch("/api/"+path,{method:"POST",headers:{"Content-Type":"application/json","Authorization":"Bearer "+S.t},body:body?JSON.stringify(body):null});return r.json();}
async function login(){const d=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:$("code").value.trim()})}).then(r=>r.json());
 if(d.ok){S.t=d.token;localStorage.token=S.t;refresh();}else toast(d.error,false);}
async function refresh(){if(!S.t)return;const d=await api("state");if(d.error==="unauthorized"){S.t="";localStorage.token="";return;}
 if(!d.ok)return;window.D=d;
 $("bal").textContent="💰 "+d.balance.toLocaleString("ru");
 $("lvl").textContent="🏅 "+d.level;$("login").style.display="none";$("app").style.display="block";$("nav").style.display="flex";
 const p=Math.min(100,Math.round(d.xp/d.xp_needed*100));$("xpbar").style.width=p+"%";
 $("xptext").textContent=d.xp+" / "+d.xp_needed+" опыта до ур. "+(d.level+1);
 $("minewait").textContent=d.mine_ready?"Руда ждёт!":"Перезарядка: "+d.mine_wait+" сек";
 $("locinfo").textContent="Локация: "+d.location;
 $("mineBtn").disabled=!d.mine_ready;
 $("bagList").innerHTML=d.backpack.map(x=>x.count>0?`<div class="row"><span>${x.name} × ${x.count}</span><span class="mut">${(x.count*x.price).toLocaleString("ru")} 🪙</span></div>`:"").join("")||"<div class='mut'>Пусто</div>";
 if(d.bag_value>0)$("bagList").innerHTML+=`<div class="row"><b>Итого</b><b>${d.bag_value.toLocaleString("ru")} 🪙</b></div>`;
 $("locList").innerHTML=d.locations.map(l=>`<div class="card"><div class="row"><b>${l.name}</b><span class="mut">×${l.mult}</span></div>${l.current?"<div class='mut'>Ты здесь</div>":l.available?`<button class="act" style="width:100%;margin-top:8px" onclick="setLoc('${l.key}')">Перейти</button>`:`<div class="mut" style="margin-top:8px">🔒 Нужен уровень ${l.min_level}</div>`}</div>`).join("");
 $("shopList").innerHTML=d.shop.filter(x=>x.price>0).map(x=>{const can=d.level>=x.level&&d.balance>=x.price;return `<div class="card"><div class="row"><b>${x.name}</b><span class="mut">${x.power} силы</span></div><div class="row"><span>${x.price.toLocaleString("ru")} 🪙</span><span class="mut">ур. ${x.level}</span></div><button class="${can?"act":"ghost"}" style="width:100%;margin-top:8px" onclick="buy('${x.key}')">${can?"Купить":"Недоступно"}</button></div>`}).join("");
 const med=["🥇","🥈","🥉"];
 $("topRich").innerHTML=d.top_rich.map((x,i)=>`<div class="row"><span>${med[i]||"▫️"} ${x[0]}</span><b>${x[1].toLocaleString("ru")}</b></div>`).join("");
 $("topLvl").innerHTML=d.top_level.map((x,i)=>`<div class="row"><span>${med[i]||"▫️"} ${x[0]}</span><b>ур. ${x[1]}</b></div>`).join("");
 $("profCard").innerHTML=`<div class="row"><span>👤 Игрок</span><b>${d.username}</b></div><div class="row"><span>⛏️ Кирка</span><b>${d.pickaxe}</b></div><div class="row"><span>🏅 Уровень</span><b>${d.level}</b></div><div class="row"><span>💰 Баланс</span><b>${d.balance.toLocaleString("ru")} 🪙</b></div>`;
 $("profLoc").textContent=d.location;
 $("profAuto").textContent=d.auto_level>0?("ур. "+d.auto_level):"нет";
 $("charList").innerHTML=d.characters.length?d.characters.map(c=>`<div class="row"><span>${c.name} <span class="mut">${c.rarity||""}</span></span><b>+${c.bonus_pct||0}%</b></div>`).join(""):"<div class='mut'>Пока никого. Персонажи выпадают при копке в боте!</div>";
 $("bonusBtn").textContent=d.bonus_ready?"Забрать бонус":"Через "+d.bonus_left;
 $("bonusBtn").className=d.bonus_ready?"act":"ghost";
 if(d.auto_level>0){
  $("autoCard").innerHTML=`<div class="row"><span>🤖 Уровень автосбора</span><b>${d.auto_level}</b></div><div class="row"><span>⏳ Следующий сбор</span><b>${d.auto_mins_left===0?"прямо сейчас":Math.floor(d.auto_mins_left/60)+" ч "+(d.auto_mins_left%60)+" мин"}</b></div><div class="row"><span>⏱ Интервал</span><b>каждые ${3} часа</b></div>`;
  $("autoBtn").textContent=d.auto_next_price?("Улучшить до ур. "+(d.auto_level+1)+" — "+d.auto_next_price.toLocaleString("ru")+" 🪙"):"Максимальный уровень";
  $("autoBtn").className=d.auto_next_price?"act":"ghost";
 }else{
  $("autoCard").innerHTML=`<div class="mut">Шахта работает сама: каждые 3 часа бот накопает руду и пришлёт уведомление в Telegram.</div>`;
  $("autoBtn").textContent="Купить автосбор — 5 000 🪙";$("autoBtn").className="act";
 }
 $("roulInfo").innerHTML=d.roulette_open?"Ставка: 10–100 000 🪙 • 2% джекпот x5, 8% x3, 20% x2, 15% возврат":"🔒 Откроется с "+d.roulette_min_level;
}
async function mine(){const d=await api("mine");if(!d.ok){toast(d.error,false);refresh();return;}
 toast((d.location?d.location+" • ":"")+d.got.map(x=>x.name+" × "+x.count).join(", ")+" • +"+d.xp+" опыта"+(d.levelup?" 🎉 Уровень "+d.level+"!":""));refresh();}
async function sell(){const d=await api("sell");if(!d.ok){toast(d.error,false);return;}toast("Продано на "+d.total.toLocaleString("ru")+" 🪙!");refresh();}
async function bonus(){const d=await api("bonus");if(!d.ok){toast(d.error,false);return;}toast("🎁 +"+d.amount.toLocaleString("ru")+" 🪙!");refresh();}
async function spin(){const d=await api("roulette",{bet:$("bet").value.trim()||null});if(d.prompt){toast("Напиши сумму ставки");return;}
 if(!d.ok){toast(d.error,false);return;}toast(d.sector+(d.delta>0?" • +"+d.delta:d.delta===0?" • возврат":" • -"+d.bet),d.delta>=0);refresh();}
async function buy(k){const d=await api("buy",{key:k});toast(d.ok?d.msg:d.error,!!d.ok);refresh();}
async function setLoc(k){const d=await api("location",{key:k});toast(d.ok?d.msg:d.error,!!d.ok);refresh();}
async function autoUp(){const d=await api("auto_upgrade",{});toast(d.ok?d.msg:d.error,!!d.ok);refresh();}
async function promo(){const d=await api("promo",{code:$("promoCode").value.trim()});toast(d.ok?d.msg:d.error,!!d.ok);if(d.ok)$("promoCode").value="";refresh();}
function tab(i,btn){document.querySelectorAll(".screen").forEach((s,j)=>s.classList.toggle("on",j===i));
 document.querySelectorAll("nav button").forEach(b=>b.classList.remove("on"));btn.classList.add("on");}
window.addEventListener("load",async()=>{
 const tg=window.Telegram&&window.Telegram.WebApp;
 if(tg&&tg.initData){
  try{tg.expand();}catch(e){}
  const r=await fetch("/api/tg_auth",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:tg.initData})});
  const d=await r.json();
  if(d.ok){S.t=d.token;localStorage.token=S.t;refresh();return;}
 }
 refresh();
});
</script></body></html>"""

# ================= ЗАПУСК =================

async def index(request):
    return web.Response(text=PAGE, content_type="text/html")


async def start_web():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS web_codes (code TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT)")
    conn.commit()
    conn.close()

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/api/login", api_login)
    app.router.add_post("/api/tg_auth", api_tg_auth)
    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/mine", api_mine)
    app.router.add_post("/api/sell", api_sell)
    app.router.add_post("/api/bonus", api_bonus)
    app.router.add_post("/api/roulette", api_roulette)
    app.router.add_post("/api/buy", api_buy)
    app.router.add_post("/api/location", api_location)
    app.router.add_post("/api/auto_upgrade", api_auto_upgrade)
    app.router.add_post("/api/promo", api_promo)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web panel on port {PORT}")


async def main():
    await start_web()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
