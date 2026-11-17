import asyncio
import os
import random
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

# ================= НАСТРОЙКИ =================
# ВСТАВЬ СЮДА СВОЙ ТОКЕН от @BotFather
TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА_ЗДЕСЬ")

# Твой ID (обязательно замени на свой числовой ID, иначе админка не сработает)
ADMIN_IDS = {5636309834}

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- НАСТРОЙКИ (значения по умолчанию) ---
MINE_COOLDOWN_SEC = 3
BONUS_AMOUNT = 5000
BONUS_COOLDOWN_HOURS = 12
ROULETTE_COOLDOWN_SEC = 30
ROULETTE_MIN_LEVEL = 20

# --- РУДА (Обновленные эмодзи и цены) ---
ORES = {
    "stone":  {"name": "🪨 Камень",        "price": 2,  "xp": 2},
    "iron":   {"name": "⚪ Железная руда",  "price": 8,  "xp": 50,
    "copper": {"name": "🟤 Медная руда",    "price": 20, "xp": 700},
    "gold":   {"name": "🟡 Золотая руда",   "price": 60000, "xp": 2500},
}
ORE_KEYS = ["stone", "iron", "copper", "gold"]

# --- КИРКИ (Твои новые цены и уровни) ---
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
            ore_gold INTEGER DEFAULT 0
        )
    """)
    # Проверка колонок (защита от старых баз)
    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_bonus_at TEXT")
    except sqlite3.OperationalError:
        pass
    for col in ["ore_stone", "ore_iron", "ore_copper", "ore_gold"]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

    # Настройки и цены
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS prices (ore_key TEXT PRIMARY KEY, price INTEGER)")

    defaults = {
        "mine_cooldown": str(MINE_COOLDOWN_SEC),
        "bonus_amount": str(BONUS_AMOUNT),
        "bonus_hours": str(BONUS_COOLDOWN_HOURS),
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

# --- СОСТОЯНИЕ РУЛЕТКИ ---
pending_roulette = {}
roulette_cooldowns = {}

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
        "ore_stone": row[8] if len(row) > 8 else 0,
        "ore_iron": row[9] if len(row) > 9 else 0,
        "ore_copper": row[10] if len(row) > 10 else 0,
        "ore_gold": row[11] if len(row) > 11 else 0,
    }

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

def seconds_until_mine(user):
    last = datetime.fromisoformat(user["last_mine_at"])
    end = last + timedelta(seconds=get_setting("mine_cooldown", MINE_COOLDOWN_SEC))
    return max(0, int((end - datetime.now()).total_seconds()))

def hours_until_bonus(user):
    last = datetime.fromisoformat(user["last_bonus_at"])
    end = last + timedelta(hours=get_setting("bonus_hours", BONUS_COOLDOWN_HOURS))
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
        [KeyboardButton(text="💼 Профиль"), KeyboardButton(text="🏆 Топ")],
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="🎲 Рулетка")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def shop_keyboard():
    kb = [[KeyboardButton(text=f"⚒️ Купить {p['name']}")] for p in PICKAXES if p["price"] > 0]
    kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ================= ОБРАБОТЧИКИ ИГРОКОВ =================

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
            "🎁 Бонус доступен раз в 12 часов.\n"
            "🎲 Рулетка откроется с 20 уровня."
        )
    else:
        if user["username"] != username:
            update_user(user_id, username=username)
        pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
        await message.answer(
            f"Снова привет, {username}! Твоя кирка: {pick['name']}, уровень {user['level']}."
        )
    await message.answer("Выбери действие:", reply_markup=main_keyboard())

# Команды-дубли (для BotFather и быстрого ввода)
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
@dp.message(Command("help"))
async def cmd_help(message: Message):
    # ============ КОД ДЛЯ ВХОДА НА САЙТ ============

@dp.message(Command("код"))
async def cmd_web_code(message: Message):
    user_id = message.from_user.id
    if not get_user(user_id):
        create_user(user_id, message.from_user.username or str(user_id))
    code = str(random.randint(100000, 999999))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS web_codes (code TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT)")
    cur.execute("INSERT OR REPLACE INTO web_codes (code, user_id, created_at) VALUES (?, ?, ?)",
                (code, user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await message.answer(f"🔑 Код для входа на сайт: <code>{code}</code>\nДействует 15 минут.", parse_mode="HTML")
    text = (
        "📜 Список команд:\n"
        "/копать — Добыть руду\n"
        "/профиль — Баланс и рюкзак\n"
        "/продать — Продать руду\n"
        "/бонус — Получить бонус\n"
        "/топ — Лучшие игроки\n"
        "/магазин — Магазин кирок\n"
        "/рулетка — Играть в рулетку\n"
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

    # Проверка порядка покупки
    if wanted_idx != current_idx + 1:
        await message.answer("Покупай по порядку: сначала каменную, потом железную и т.д.")
        return

    if user["level"] < wanted["level"]:
        await message.answer(
            f"Не хватает уровня. Нужен уровень {wanted['level']}, у тебя {user['level']}."
        )
        return

    if user["balance"] < wanted["price"]:
        await message.answer(f"Не хватает монет. Нужно {wanted['price']}, у тебя {user['balance']}.")
        return

    new_balance = user["balance"] - wanted["price"]
    update_user(user_id, balance=new_balance, pickaxe_key=wanted["key"])
    await message.answer(f"✅ Ты купил кирку: {wanted['name']}! Теперь копается лучше.")

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
    text = (
        f"👤 Профиль игрока {user['username']}\n"
        f"💰 Баланс: {user['balance']} монет\n"
        f"📈 Опыт: {user['xp']} / {needed} до уровня {user['level'] + 1}\n"
        f"🏅 Уровень: {user['level']}\n"
        f"⛏️ Твоя кирка: {pick['name']}\n"
        f"🎒 Рюкзак: {backpack}\n"
        f"⏰ Бонус: {'доступен' if can_bonus(user) else 'ещё не скоро'}\n"
        f"🎲 Рулетка: {'открыта' if user['level'] >= ROULETTE_MIN_LEVEL else f'с {ROULETTE_MIN_LEVEL} уровня'}"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "🛒 Магазин")
async def shop(message: Message):
    lines = ["🛒 Магазин кирок (цена + требование уровня):"]
    for p in PICKAXES:
        if p["price"] > 0:
            lines.append(f"• {p['name']} — {p['price']} монет, нужен {p['level']} уровень")
    await message.answer("\n".join(lines), reply_markup=shop_keyboard())

@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: Message):
    await message.answer("Главное меню:", reply_markup=main_keyboard())

# ================= АДМИН-ПАНЕЛЬ (ВНУТРИ БОТА) =================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет прав администратора!")
        return

    text = (
        "🛠 Админ-панель\n\n"
        "💰 /give <id> <type> <amount> — Выдать игроку (money/xp/ore)\n"
        "🗑 /reset <id> — Сбросить прогресс игрока\n"
        "⚙️ /set_config <key> <value> — Изменить настройки (кулдаун, бонус и т.д.)\n"
        "💎 /set_price <ore_key> <price> — Изменить цену руды\n"
        "📊 /stats — Общая статистика бота"
    )
    await message.answer(text)

# /give <id> <type> <amount>
# Пример: /give 123456 money 10000
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

# /reset <id>
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
        last_mine_at=None, last_bonus_at=None
    )
    await message.answer(f"🗑 Прогресс игрока {target_id} сброшен.")

# /set_config <key> <value>
# Ключи: mine_cooldown, bonus_amount, bonus_hours
@dp.message(Command("set_config"))
async def cmd_set_config(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) != 3:
        await message.answer("❌ Формат: /set_config <ключ> <значение>\nКлючи: mine_cooldown, bonus_amount, bonus_hours")
        return

    key = args[1]
    try:
        value = int(args[2])
    except ValueError:
        await message.answer("❌ Значение должно быть числом.")
        return

    set_setting(key, value)
    await message.answer(f"✅ Настройка '{key}' установлена в {value}")

# /set_price <ore_key> <price>
# Ключи: stone, iron, copper, gold
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

# /stats
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

# ============ РУССКИЕ КОМАНДЫ (вводятся вручную) ============

@dp.message(Command("копать"))
async def cmd_ru_mine(message: Message): await mine_action(message)

@dp.message(Command("профиль"))
async def cmd_ru_profile(message: Message): await profile(message)

@dp.message(Command("продать"))
async def cmd_ru_sell(message: Message): await sell_ore(message)

@dp.message(Command("бонус"))
async def cmd_ru_bonus(message: Message): await bonus_action(message)

@dp.message(Command("топ"))
async def cmd_ru_top(message: Message): await top_players(message)

@dp.message(Command("магазин"))
async def cmd_ru_shop(message: Message): await shop(message)

@dp.message(Command("рулетка"))
async def cmd_ru_roulette(message: Message): await roulette_start(message)

@dp.message(Command("команды"))
async def cmd_ru_help(message: Message):
    text = (
        "📜 Команды бота:\n"
        "/копать — добыть руду\n"
        "/профиль — баланс и рюкзак\n"
        "/продать — продать руду\n"
        "/бонус — получить бонус\n"
        "/топ — лучшие игроки\n"
        "/магазин — магазин кирок\n"
        "/рулетка — играть в рулетку"
    )
    await message.answer(text, reply_markup=main_keyboard())

# --- админские на русском ---
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

