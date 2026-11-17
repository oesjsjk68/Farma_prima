import os
import json
import hmac
import hashlib
import secrets
import sqlite3
import urllib.parse

from flask import Flask, redirect, render_template_string, request, session, url_for

# --- КОНФИГУРАЦИЯ ---
# Твой Telegram ID — админ панели
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", "5636309834"))
# Токен бота — нужен для проверки подписи Telegram Mini App
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(SCRIPT_DIR, "bot_db.sqlite")

PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)

ORE_NAMES = {
    "stone": "Камень",
    "iron": "Железная руда",
    "copper": "Медная руда",
    "gold": "Золотая руда",
}
PICK_NAMES = {
    "wood": "Деревянная", "stone": "Каменная", "iron": "Железная",
    "gold": "Золотая", "diamond": "Алмазная",
}
DEFAULT_SETTINGS = {
    "mine_cooldown": "60",
    "bonus_amount": "5000",
    "bonus_hours": "12",
    "roulette_min_level": "20",
    "roulette_cooldown": "30",
    "roulette_min_bet": "10",
    "roulette_max_bet": "100000",
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
        return False, "Игрок {} не найден.".format(user_id)
    if resource == "coins":
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    elif resource in ORE_NAMES:
        col = "ore_" + resource
        cur.execute("UPDATE users SET {} = {} + ? WHERE user_id = ?".format(col, col), (amount, user_id))
    else:
        conn.close()
        return False, "Неизвестный ресурс: " + str(resource)
    conn.commit()
    conn.close()
    return True, "Выдано {} игроку {}.".format(amount, user_id)


def do_reset(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        conn.close()
        return False, "Игрок {} не найден.".format(user_id)
    cur.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True, "Баланс игрока {} сброшен.".format(user_id)


# --- ПРОВЕРКА ДАННЫХ TELEGRAM MINI APP ---
def verify_init_data(init_data):
    """Проверяет подпись initData от Telegram."""
    if not init_data or not BOT_TOKEN:
        return False
    pairs = []
    received_hash = None
    for chunk in init_data.split("&"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        if key == "hash":
            received_hash = value
        else:
            pairs.append(key + "=" + value)
    if received_hash is None:
        return False
    pairs.sort()
    data_check_string = "\n".join(pairs)
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc_hash, received_hash)


def extract_user_id(init_data):
    """Достаёт id пользователя из initData."""
    try:
        for chunk in init_data.split("&"):
            if chunk.startswith("user="):
                user_json = urllib.parse.unquote(chunk[len("user="):])
                user = json.loads(user_json)
                return int(user.get("id", 0))
    except Exception:
        return None
    return None


def is_admin():
    if session.get("logged_in"):
        return True
    return bool(session.get("is_tg_auth")) and session.get("tg_user_id") == ADMIN_TG_ID


# --- ШАБЛОНЫ ---
LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Вход</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;display:flex;justify-content:center;padding-top:80px}
form{background:#2b2b3d;padding:30px;border-radius:12px}
input{padding:8px;width:200px}button{padding:8px 20px;margin-top:10px}</style></head>
<body><form method="post">
<h2>🔑 Вход в панель</h2>
<p style="color:#f66">{{ error }}</p>
<input type="password" name="password" placeholder="Пароль" autofocus><br>
<button>Войти</button>
</form></body></html>"""

ADMIN_PANEL_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Панель шахты</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;max-width:820px;margin:30px auto;padding:0 15px}
input{padding:6px;width:110px}button{padding:8px 20px;margin-top:12px}
table{border-collapse:collapse;margin-top:15px;font-size:14px}td,th{border:1px solid #555;padding:6px 12px}
h3{margin-top:25px}
.box{background:#2b2b3d;padding:15px 20px;border-radius:10px;margin-top:15px}
.msg{color:#7fd57f;margin-top:10px}
.msg-err{color:#f66;margin-top:10px}
select{padding:6px;background:#3a3a4d;color:#eee;border:1px solid #555}
code{color:#8ab}
</style></head><body>
<h2>⚙️ Панель шахты (админ)</h2>

<div class="box">
<h3 style="margin-top:0">🎁 Выдать игроку</h3>
<form method="post" action="/admin">
<input type="hidden" name="action" value="give">
ID игрока: <input name="user_id" placeholder="например 5636309834"><br>
Что выдать: <select name="resource">
<option value="coins">Монеты</option>
<option value="stone">Камень</option>
<option value="iron">Железная руда</option>
<option value="copper">Медная руда</option>
<option value="gold">Золотая руда</option>
</select><br>
Количество: <input name="amount" placeholder="например 100"><br>
<button>Выдать</button>
</form>
{% if give_msg %}<p class="msg">{{ give_msg }}</p>{% endif %}
{% if give_err %}<p class="msg-err">{{ give_err }}</p>{% endif %}
</div>

<div class="box">
<h3 style="margin-top:0">🔄 Сбросить баланс игроку</h3>
<form method="post" action="/admin" onsubmit="return confirm('Точно сбросить баланс?')">
<input type="hidden" name="action" value="reset">
ID игрока: <input name="user_id" placeholder="ID игрока"><br>
<button>Сбросить баланс</button>
</form>
{% if reset_msg %}<p class="msg">{{ reset_msg }}</p>{% endif %}
{% if reset_err %}<p class="msg-err">{{ reset_err }}</p>{% endif %}
</div>

<form method="post" action="/admin">
<input type="hidden" name="action" value="save">
<h3>Настройки шахты</h3>
Кулдаун накопания (сек): <input name="mine_cooldown" value="{{ settings.mine_cooldown }}"><br>
Бонус (монет): <input name="bonus_amount" value="{{ settings.bonus_amount }}"><br>
Бонус раз в (часов): <input name="bonus_hours" value="{{ settings.bonus_hours }}"><br>
<h3>Цены руды</h3>
{% for key, price in prices.items() %}{{ names[key] }}: <input name="price_{{ key }}" value="{{ price }}"><br>{% endfor %}
<h3>Настройки рулетки</h3>
Мин. уровень для рулетки: <input name="roulette_min_level" value="{{ settings.roulette_min_level }}"><br>
Кулдаун рулетки (сек): <input name="roulette_cooldown" value="{{ settings.roulette_cooldown }}"><br>
Мин. ставка: <input name="roulette_min_bet" value="{{ settings.roulette_min_bet }}"><br>
Макс. ставка: <input name="roulette_max_bet" value="{{ settings.roulette_max_bet }}"><br>
<button>💾 Сохранить настройки</button>
</form>

<h3>Игроки</h3>
<table><tr><th>ID</th><th>Игрок</th><th>Монеты</th><th>Уровень</th><th>Кирка</th><th>Рюкзак</th></tr>
{% for p in players %}<tr>
<td><code>{{ p[0] }}</code></td><td>{{ p[1] }}</td><td>{{ p[2] }}</td><td>{{ p[3] }}</td><td>{{ picks[p[4]] }}</td>
<td>🪨{{ p[5] }} ⚙️{{ p[6] }} 🥉{{ p[7] }} 💎{{ p[8] }}</td>
</tr>{% endfor %}</table>
<p><a href="/logout" style="color:#8ab">Выйти</a></p>
</body></html>"""

PLAYER_PROFILE_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Профиль</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;max-width:600px;margin:30px auto;padding:0 15px}
table{border-collapse:collapse;margin-top:15px;font-size:14px}td,th{border:1px solid #555;padding:6px 12px}
h2{text-align:center}
.box{background:#2b2b3d;padding:15px;border-radius:10px;text-align:center}
code{color:#8ab}
</style></head><body>
<h2>👤 Профиль игрока</h2>
<div class="box">
<p>ID: <code>{{ user_id }}</code></p>
<p>Ник: {{ username }}</p>
<p>Баланс: {{ balance }} 💰</p>
<p>Уровень: {{ level }}</p>
<p>Кирка: {{ pickaxe }}</p>
<p>Рюкзак: 🪨{{ stone }} ⚙️{{ iron }} 🥉{{ copper }} 💎{{ gold }}</p>
</div>
<h3 style="text-align:center">Топ игроков</h3>
<table><tr><th>Игрок</th><th>Баланс</th><th>Уровень</th><th>Кирка</th></tr>
{% for p in top_players %}<tr>
<td>{{ p[1] }}</td><td>{{ p[2] }}</td><td>{{ p[3] }}</td><td>{{ picks[p[4]] }}</td>
</tr>{% endfor %}</table>
</body></html>"""


def render_panel(settings, prices, players, give_msg="", give_err="", reset_msg="", reset_err=""):
    return render_template_string(
        ADMIN_PANEL_PAGE, settings=settings, prices=prices, players=players,
        names=ORE_NAMES, picks=PICK_NAMES,
        give_msg=give_msg, give_err=give_err,
        reset_msg=reset_msg, reset_err=reset_err,
    )


def render_player_profile(row, top_players):
    user_id, username, balance, level, pickaxe_key, stone, iron, copper, gold = row
    return render_template_string(
        PLAYER_PROFILE_PAGE, user_id=user_id, username=username,
        balance=balance, level=level, pickaxe=PICK_NAMES.get(pickaxe_key, pickaxe_key),
        stone=stone, iron=iron, copper=copper, gold=gold,
        top_players=top_players, picks=PICK_NAMES,
    )


# --- МАРШРУТЫ ---
@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/")
def index():
    # 1. Открыли из Telegram (кнопка меню шлёт tgWebAppData в URL)
    raw = request.args.get("tgWebAppData") or request.args.get("initData")
    if raw:
        init_data = urllib.parse.unquote(raw)
        if not verify_init_data(init_data):
            return "Ошибка безопасности: данные Telegram не прошли проверку.", 403
        tg_id = extract_user_id(init_data)
        if not tg_id:
            return "Не удалось получить пользователя из Telegram.", 400
        session["is_tg_auth"] = True
        session["tg_user_id"] = tg_id
        session["logged_in"] = tg_id == ADMIN_TG_ID
        if tg_id == ADMIN_TG_ID:
            return redirect(url_for("admin_panel"))
        return redirect(url_for("profile"))

    # 2. Уже авторизован
    if session.get("logged_in"):
        return redirect(url_for("admin_panel"))
    if session.get("is_tg_auth"):
        return redirect(url_for("profile"))

    # 3. Обычный браузер — вход по паролю
    return redirect(url_for("login"))


@app.route("/admin", methods=["GET", "POST"])
def admin_panel():
    if not is_admin():
        return redirect(url_for("login"))

    give_msg = give_err = reset_msg = reset_err = ""

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "give":
            try:
                uid = int(request.form.get("user_id", "0"))
                amount = int(request.form.get("amount", "0"))
                resource = request.form.get("resource", "coins")
                ok, msg = do_give(uid, resource, amount)
                if ok:
                    give_msg = msg
                else:
                    give_err = msg
            except ValueError:
                give_err = "ID и количество должны быть числами."
        elif action == "reset":
            try:
                uid = int(request.form.get("user_id", "0"))
                ok, msg = do_reset(uid)
                if ok:
                    reset_msg = msg
                else:
                    reset_err = msg
            except ValueError:
                reset_err = "ID должен быть числом."
        elif action == "save":
            conn = get_conn()
            cur = conn.cursor()
            for key in DEFAULT_SETTINGS:
                val = request.form.get(key)
                if val:
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val))
            for key in DEFAULT_PRICES:
                val = request.form.get("price_" + key)
                if val:
                    try:
                        cur.execute("INSERT OR REPLACE INTO prices (ore_key, price) VALUES (?, ?)", (key, int(val)))
                    except ValueError:
                        pass
            conn.commit()
            conn.close()
            give_msg = "Настройки сохранены!"

    settings, prices, players = load_all()
    return render_panel(settings, prices, players, give_msg, give_err, reset_msg, reset_err)


@app.route("/profile")
def profile():
    tg_id = session.get("tg_user_id")
    if not tg_id:
        return redirect(url_for("login"))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT user_id, username, balance, level, pickaxe_key,
                          ore_stone, ore_iron, ore_copper, ore_gold
                   FROM users WHERE user_id = ?""", (tg_id,))
    row = cur.fetchone()
    cur.execute("""SELECT user_id, username, balance, level, pickaxe_key
                   FROM users ORDER BY balance DESC LIMIT 10""")
    top_players = cur.fetchall()
    conn.close()
    if not row:
        return "Вы ещё не зарегистрированы в игре — напишите боту /start.", 404
    return render_player_profile(row, top_players)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if not PANEL_PASSWORD:
        return "Панель не настроена: задай переменную PANEL_PASSWORD (или открой панель через кнопку бота).", 500
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin_panel"))
        error = "Неверный пароль"
    return render_template_string(LOGIN_PAGE, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8888)
