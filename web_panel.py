import os
import secrets
import sqlite3
import hmac
import hashlib
from flask import Flask, redirect, render_template_string, request, session, url_for, abort

# --- КОНФИГУРАЦИЯ ---
# Твой Telegram ID (число). Узнай у бота @userinfobot. 
# Без этого ты не увидишь админку внутри приложения.
ADMIN_TG_ID = 5636309834 

# Токен бота (нужен для проверки подписи initData). 
# Возьми в BotFather -> Bot Settings -> Domain -> Web App Secret Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "") 

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(SCRIPT_DIR, "bot_db.sqlite")

PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

ORE_NAMES = {
    "stone": "Камень", "iron": "Железная руда",
    "copper": "Медная руда", "gold": "Золотая руда"
}
PICK_NAMES = {
    "wood": "Деревянная", "stone": "Каменная", "iron": "Железная",
    "gold": "Золотая", "diamond": "Алмазная"
}
DEFAULT_SETTINGS = {
    "mine_cooldown": "60", "bonus_amount": "5000", "bonus_hours": "12",
    "roulette_min_level": "20", "roulette_cooldown": "30",
    "roulette_min_bet": "10", "roulette_max_bet": "100000"
}
DEFAULT_PRICES = {"stone": 2, "iron": 8, "copper": 20, "gold": 60}

def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def ensure_tables():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS prices (ore_key TEXT PRIMARY KEY, price INTEGER)")
    for k, v in DEFAULT_SETTINGS.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    for k, v in DEFAULT_PRICES.items():
        cur.execute("INSERT OR IGNORE INTO prices (ore_key, price) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def load_all():
    ensure_tables()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    settings = dict(cur.fetchall())
    cur.execute("SELECT ore_key, price FROM prices")
    prices = dict(cur.fetchall())
    cur.execute("""SELECT user_id, username, balance, level, pickaxe_key,
                          ore_stone, ore_iron, ore_copper, ore_gold
                   FROM users ORDER BY balance DESC""")
    players = cur.fetchall()
    conn.close()
    return settings, prices, players

def do_give(user_id, resource, amount):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        conn.close()
        return False, f"Игрок {user_id} не найден."
    if resource == "coins":
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    else:
        col = f"ore_{resource}"
        cur.execute(f"UPDATE users SET {col} = {col} + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()
    return True, f"Выдано {amount} игроку {user_id}."

# --- ЛОГИКА TELEGRAM MINI APP ---
def verify_telegram_data(data: str) -> bool:
    """Проверяет подпись initData от Telegram"""
    if not data:
        return False
    
    parsed_data = {}
    for item in data.split('&'):
        if '=' in item:
            key, value = item.split('=', 1)
            parsed_data[key] = value
    
    if 'hash' not in parsed_data:
        return False
        
    data_check_arr = parsed_data['hash'].split('\n')
    hash_value = data_check_arr.pop(0)
    
    # Формируем секретный ключ
    secret_key = hmac.new(
        b"WebAppData", 
        key=BOT_TOKEN.encode(), 
        digestmod=hashlib.sha256
    ).digest()
    
    # Формируем проверочную строку
    check_hash = hmac.new(
        secret_key, 
        '\n'.join(data_check_arr).encode(), 
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(check_hash, hash_value)

def get_user_from_initdata(data: str):
    """Извлекает user_id из initData"""
    try:
        import json
        # В initData данные пользователя часто идут в поле user
        # Но проще распарсить всю строку и найти user_id, если он там есть отдельно,
        # либо распарсить JSON из поля user.
        # Стандартный формат: user={...}&hash=...
        
        # Простой парсинг: ищем user= и берем JSON
        if 'user=' in data:
            user_part = data.split('user=').split('&')
            # URL decode не всегда нужен, если данные приходят уже декодированными, 
            # но для надежности можно использовать urllib.parse.unquote
            import urllib.parse
            user_json = urllib.parse.unquote(user_part)
            user_data = json.loads(user_json)
            return user_data.get('id')
    except Exception:
        pass
    return None

# --- ШАБЛОНЫ ---
LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Вход</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;display:flex;justify-content:center;padding-top:80px}
form{background:#2b2b3d;padding:30px;border-radius:12px}
input{padding:8px;width:200px}button{padding:8px 20px;margin-top:10px}</style></head>
<body><form method="post"><h2>🔑 Вход в панель</h2>
<p style="color:#f66">{{ error }}</p>
<input type="password" name="password" placeholder="Пароль" autofocus><br>
<button>Войти</button></form></body></html>"""

ADMIN_PANEL_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Панель шахты</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;max-width:820px;margin:30px auto;padding:0 15px}
input{padding:6px;width:110px}button{padding:8px 20px;margin-top:12px}
table{border-collapse:collapse;margin-top:15px;font-size:14px}td,th{border:1px solid #555;padding:6px 12px}
h3{margin-top:25px}.box{background:#2b2b3d;padding:15px 20px;border-radius:10px;margin-top:15px}
.msg{color:#7fd57f;margin-top:10px}.msg-err{color:#f66;margin-top:10px}
select{padding:6px;background:#3a3a4d;color:#eee;border:1px solid #555}
code{color:#8ab}</style><body>
<h2>⚙️ Панель шахты (Админ)</h2>
<p>Ты залогинен как Админ (ID: {{ admin_id }})</p>
<div class="box"><h3 style="margin-top:0">🎁 Выдать игроку</h3>
<form method="post" action="/give"><input name="user_id" placeholder="ID игрока"><br>
<select name="resource"><option value="coins">Монеты</option>
<option value="stone">Камень</option><option value="iron">Железная руда</option>
<option value="copper">Медная руда</option><option value="gold">Золотая руда</option></select><br>
<input name="amount" placeholder="Количество"><br><button>Выдать</button></form>
{% if give_msg %}<p class="msg">{{ give_msg }}</p>{% endif %}
{% if give_err %}<p class="msg-err">{{ give_err }}</p>{% endif %}</div>
<div class="box"><h3 style="margin-top:0">🔄 Сбросить баланс</h3>
<form method="post" action="/reset" onsubmit="return confirm('Точно сбросить?')">
<input name="user_id" placeholder="ID игрока"><br><button>Сбросить баланс</button></form>
{% if reset_msg %}<p class="msg">{{ reset_msg }}</p>{% endif %}
{% if reset_err %}<p class="msg-err">{{ reset_err }}</p>{% endif %}</div>
<form method="post" action="/save"><h3>Настройки шахты</h3>
Кулдаун: <input name="mine_cooldown" value="{{ settings.mine_cooldown }}"><br>
Бонус: <input name="bonus_amount" value="{{ settings.bonus_amount }}"><br>
Бонус часов: <input name="bonus_hours" value="{{ settings.bonus_hours }}"><br>
<h3>Цены руды</h3>
{% for key, price in prices.items() %}{{ names[key] }}: <input name="price_{{ key }}" value="{{ price }}"><br>{% endfor %}
<h3>Рулетка</h3>
Мин. ур: <input name="roulette_min_level" value="{{ settings.roulette_min_level }}"><br>
Кулдаун: <input name="roulette_cooldown" value="{{ settings.roulette_cooldown }}"><br>
Мин. ставка: <input name="roulette_min_bet" value="{{ settings.roulette_min_bet }}"><br>
Макс. ставка: <input name="roulette_max_bet" value="{{ settings.roulette_max_bet }}"><br>
<button>💾 Сохранить</button></form>
<h3>Игроки</h3>
<table><tr><th>ID</th><th>Игрок</th><th>Монеты</th><th>Ур</th><th>Кирка</th><th>Рюкзак</th></tr>
{% for p in players %}<tr><td><code>{{ p }}</code></td><td>{{ p }}</td><td>{{ p }}</td>
<td>{{ p }}</td><td>{{ picks[p] }}</td><td>🪨{{ p }} ⚙️{{ p }} 🥉{{ p }} 💎{{ p }}</td></tr>{% endfor %}</table>
<p><a href="/logout" style="color:#8ab">Выйти</a></p></body></html>"""

PLAYER_PROFILE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Профиль</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;max-width:600px;margin:30px auto;padding:0 15px}
table{border-collapse:collapse;margin-top:15px;font-size:14px}td,th{border:1px solid #555;padding:6px 12px}
h2{text-align:center}.box{background:#2b2b3d;padding:15px;border-radius:10px;text-align:center}
code{color:#8ab}</style><body>
<h2>👤 Профиль игрока</h2>
<div class="box">
<p>ID: <code>{{ user_id }}</code></p>
<p>Баланс: {{ balance }} 💰</p>
<p>Уровень: {{ level }}</p>
<p>Кирка: {{ pickaxe }}</p>
<p>Рюкзак: 🪨{{ stone }} ⚙️{{ iron }} 🥉{{ copper }} 💎{{ gold }}</p>
</div>
<h3>Топ игроков</h3>
<table><tr><th>ID</th><th>Игрок</th><th>Баланс</th><th>Ур</th><th>Кирка</th></tr>
{% for p in top_players %}<tr><td><code>{{ p }}</code></td><td>{{ p }}</td><td>{{ p }}</td><td>{{ p }}</td><td>{{ picks[p] }}</td></tr>{% endfor %}</table>
<p style="text-align:center;margin-top:20px;"><a href="/logout" style="color:#8ab">Выйти</a></p>
</body></html>"""

def render_admin(settings, prices, players, give_msg, give_err, reset_msg, reset_err):
    return render_template_string(
        ADMIN_PANEL_PAGE, settings=settings, prices=prices, players=players,
        names=ORE_NAMES, picks=PICK_NAMES,
        give_msg=give_msg, give_err=give_err,
        reset_msg=reset_msg, reset_err=reset_err,
        admin_id=ADMIN_TG_ID
    )

def render_player(user_id, balance, level, pickaxe, stone, iron, copper, gold, top_players):
    return render_template_string(
        PLAYER_PROFILE_PAGE, user_id=user_id, balance=balance, level=level,
        pickaxe=pickaxe, stone=stone, iron=iron, copper=copper, gold=gold,
        top_players=top_players, picks=PICK_NAMES
    )

# --- МАРШРУТЫ ---

@app.route("/healthz")
def healthz():
    return "ok"

@app.route("/", methods=["GET", "POST"])
def index():
    # 1. Проверяем, пришли ли мы из Telegram
    init_data = request.args.get('initData')
    
    # Если есть initData, пытаемся войти через Telegram
    if init_data:
        if not verify_telegram_data(init_data):
            return "Ошибка безопасности Telegram. Данные подделаны.", 403
        
        tg_user_id = get_user_from_initdata(init_data)
        if not tg_user_id:
            return "Не удалось получить данные пользователя из Telegram.", 400
            
        # Сохраняем ID в сессию для дальнейших действий
        session['tg_user_id'] = tg_user_id
        session['is_tg_auth'] = True
        
        # Если это админ - показываем админку, иначе профиль
        if tg_user_id == ADMIN_TG_ID:
            return redirect(url_for('admin_panel'))
        else:
            return redirect(url_for('player_profile'))

    # 2. Если не из Telegram (обычный браузер) - проверяем сессию или пароль
    if session.get('logged_in'):
        return redirect(url_for('admin_panel'))
        
    return redirect(url_for('login'))

@app.route("/admin", methods=["GET", "POST"])
def admin_panel():
    # Защита: только если залогинен (пароль ИЛИ TG)
    if not session.get('logged_in') and not (session.get('is_tg_auth') and session.get('tg_user_id') == ADMIN_TG_ID):
        return redirect(url_for('login'))

    settings, prices, players = load_all()
    give_msg = give_err = reset_msg = reset_err = ""

    if request.method == "POST":
        action = request.form.get('action')
        if action == 'give':
            uid = request.form.get('user_id')
            res = request.form.get('resource')
            amt = request.form.get('amount')
            if uid and res and amt:
                success, msg = do_give(uid, res, int(amt))
                if success: give_msg = msg
                else: give_err = msg
        elif action == 'reset':
            uid = request.form.get('user_id')
            if uid:
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (uid,))
                conn.commit()
                conn.close()
                reset_msg = f"Баланс игрока {uid} сброшен."
        elif action == 'save':
            conn = get_conn()
            cur = conn.cursor()
            # Сохраняем настройки
            for key in DEFAULT_SETTINGS.keys():
                val = request.form.get(key)
                if val: cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val))
            # Сохраняем цены
            for key in DEFAULT_PRICES.keys():
                val = request.form.get(f"price_{key}")
                if val: cur.execute("INSERT OR REPLACE INTO prices (ore_key, price) VALUES (?, ?)", (key, int(val)))
            conn.commit()
            conn.close()
            settings, prices, players = load_all() # Перечитываем
            give_msg = "Настройки сохранены!"

    return render_admin(settings, prices, players, give_msg, give_err, reset_msg, reset_err)

@app.route("/profile")
def player_profile():
    # Защита: только если залогинен через TG или имеет сессию
    if not session.get('is_tg_auth') and not session.get('logged_in'):
        return redirect(url_for('login'))
    
    tg_id = session.get('tg_user_id')
    if not tg_id:
        # Если зашли через пароль, но пытаемся попасть в профиль игрока - редирект на админку или ошибку
        # Для простоты, если не из TG, то это админ
        return redirect(url_for('admin_panel'))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, balance, level, pickaxe_key, ore_stone, ore_iron, ore_copper, ore_gold FROM users WHERE user_id = ?", (tg_id,))
    user = cur.fetchone()
    conn.close()

    if not user:
        return "Вы еще не зарегистрированы в игре. Начните игру в боте.", 404

    # Топ игроков
    cur = get_conn().cursor()
    cur.execute("SELECT user_id, username, balance, level, pickaxe_key FROM users ORDER BY balance DESC LIMIT 10")
    top_players = cur.fetchall()
    get_conn().close()

    return render_player(tg_id, user, user, user, user, user, user, user, top_players)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if not PANEL_PASSWORD:
        return "Ошибка: не задан PANEL_PASSWORD", 500
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin_panel"))
        error = "Неверный пароль"
    return render_template_string(LOGIN_PAGE, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/give", methods=["POST"])
def give_post():
    # Дублируем логику для POST формы, если она отправляется напрямую
    # В идеале все формы должны вести на /admin, где обрабатывается POST
    return redirect(url_for('admin_panel'))

@app.route("/reset", methods=["POST"])
def reset_post():
    return redirect(url_for('admin_panel'))

@app.route("/save", methods=["POST"])
def save_post():
    return redirect(url_for('admin_panel'))

if __name__ == "main":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8888)))
