import os
import asyncio
import secrets
from datetime import datetime, timedelta
from threading import Thread

import sqlite3
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from flask import Flask, request, jsonify, render_template_string

# ================= НАСТРОЙКИ =================
TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА_ЗДЕСЬ")
ADMIN_IDS = {5636309834}

bot = Bot(token=TOKEN)
dp = Dispatcher()

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
    # миграции
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
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))

def create_user(user_id, username=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def update_user(user_id, **kwargs):
    conn = get_conn()
    cur = conn.cursor()
    sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
    values = list(kwargs.values()) + [user_id]
    cur.execute(f"UPDATE users SET {sets} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

# Хранилище кодов входа
LOGIN_CODES = {}
CODE_LIFETIME_MINUTES = 15

def generate_login_code(user_id: int) -> str:
    code = str(secrets.randbelow(1_000_000)).zfill(6)
    expires_at = datetime.now() + timedelta(minutes=CODE_LIFETIME_MINUTES)
    LOGIN_CODES[code] = {
        "user_id": user_id,
        "expires_at": expires_at,
        "used": False,
    }
    return code

# ================= БОТ: КОМАНДЫ И КЛАВИАТУРЫ =================

def main_keyboard():
    kb = [
        [KeyboardButton(text="⛏️ Накопать")],
        [KeyboardButton(text="💰 Продать руду"), KeyboardButton(text="🎁 Бонус")],
        [KeyboardButton(text="📦 Кейс"), KeyboardButton(text="🏆 Топ")],
        [KeyboardButton(text="🖥 Панель"), KeyboardButton(text="💼 Профиль")],
        [KeyboardButton(text="⚙️ Админ")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    create_user(message.from_user.id, message.from_user.username or str(message.from_user.id))
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n"
        "Выбирай действие на кнопках:",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "🖥 Панель")
async def cmd_panel(message: Message):
    user_id = message.from_user.id
    create_user(user_id, message.from_user.username or str(user_id))
    code = generate_login_code(user_id)
    await message.answer(
        f"🔐 Код для входа в веб‑панель: <b>{code}</b>\n\n"
        f"⏳ Действует {CODE_LIFETIME_MINUTES} минут.\n"
        f"🌐 Введи его на странице панели, чтобы открыть профиль и копать через интерфейс.",
        parse_mode="HTML"
    )

# Сюда можно добавить остальные команды (копать, профиль и т.д.)
# Для краткости я оставил только самое важное для панели.
# Остальные хендлеры (копать, рулетка, магазин) оставь из своего старого кода.

# ================= ВЕБ‑ПАНЕЛЬ (FLASK) =================

app = Flask(__name__)

# Простая HTML‑страница входа (можно позже вынести в отдельный файл)
LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head><title>Вход в панель</title><style>
    body { font-family: sans-serif; padding: 40px; text-align: center; }
    input { padding: 10px; font-size: 16px; }
    button { padding: 10px 20px; font-size: 16px; background: #0088cc; color: white; border: none; cursor: pointer; }
    .error { color: red; margin-top: 10px; }
</style></head>
<body>
    <h1>🖥 Вход в панель игрока</h1>
    <form id="loginForm">
        <input type="text" id="code" placeholder="Введи 6‑значный код из бота" maxlength="6">
        <br><br>
        <button type="submit">Войти</button>
    </form>
    <div id="msg" class="error"></div>
    <script>
        document.getElementById('loginForm').onsubmit = async (e) => {
            e.preventDefault();
            const code = document.getElementById('code').value.trim();
            const res = await fetch('/api/login', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({code}) });
            const data = await res.json();
            if (data.ok) {
                window.location.href = '/panel?user_id=' + data.user_id;
            } else {
                document.getElementById('msg').innerText = data.message || 'Ошибка входа';
            }
        };
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return LOGIN_PAGE

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    code = data.get("code", "")
    if len(code) != 6 or not code.isdigit():
        return jsonify({"ok": False, "message": "Неверный формат кода"}), 400

    entry = LOGIN_CODES.get(code)
    if not entry:
        return jsonify({"ok": False, "message": "Код не найден или истёк"}), 403
    if entry["used"]:
        return jsonify({"ok": False, "message": "Этот код уже использован"}), 403
    if datetime.now() > entry["expires_at"]:
        # Истекает — удаляем
        LOGIN_CODES.pop(code, None)
        return jsonify({"ok": False, "message": "Срок действия кода истёк"}), 403

    # Помечаем как использованный
    entry["used"] = True
    return jsonify({"ok": True, "user_id": entry["user_id"]})

@app.route("/panel")
def panel():
    user_id_str = request.args.get("user_id")
    if not user_id_str or not user_id_str.isdigit():
        return "Неверный запрос", 400
    user_id = int(user_id_str)
    user = get_user(user_id)
    if not user:
        return "Игрок не найден", 404

    # Пример простой панели — можно дорабатывать
    html = f"""
    <!DOCTYPE html><html><head><title>Панель игрока</title><style>
        body {{ font-family: sans-serif; padding: 20px; }}
        .card {{ border: 1px solid #ccc; padding: 15px; margin: 10px 0; }}
    </style></head><body>
        <h1>💼 Панель игрока</h1>
        <div class="card"><b>ID:</b> {user["user_id"]}</div>
        <div class="card"><b>Баланс:</b> {user["balance"]} монет</div>
        <div class="card"><b>Опыт:</b> {user["xp"]} XP, уровень {user["level"]}</div>
        <div class="card">
            <b>Руда:</b><br>
            🪨 Камень: {user["ore_stone"]}<br>
            ⚪ Железо: {user["ore_iron"]}<br>
            🟤 Медь: {user["ore_copper"]}<br>
            🟡 Золото: {user["ore_gold"]}
        </div>
        <p>Здесь можно добавить кнопки «Копать», «Продать», «Магазин» и т.п.</p>
        <a href="/">← Назад к входу</a>
    </body></html>
    """
    return html

# ================= ЗАПУСК =================

def run_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)

async def run_bot():
    await dp.start_polling(bot)

def main():
    # Запускаем Flask в отдельном потоке
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Бот в основном потоке (asyncio)
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
