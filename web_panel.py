import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import urllib.parse

from flask import Flask, redirect, render_template_string, request, session, url_for

# --- ПУТИ И КЛЮЧИ ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(SCRIPT_DIR, "bot_db.sqlite")

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА_ЗДЕСЬ")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
ADMIN_IDS = {5636309834}  # <-- твой chat_id (как в bot.py)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

ORE_NAMES = {
    "stone": "Камень",
    "iron": "Железная руда",
    "copper": "Медная руда",
    "gold": "Золотая руда",
}
ORE_ICONS = {"stone": "🪨", "iron": "⚪", "copper": "🟤", "gold": "🟡"}
PICK_NAMES = {
    "wood": "⛏️", "stone": "⛏️", "iron": "Железная",
    "gold": "⛏️", "diamond": "⛏️",
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
        return False, f"Игрок {user_id} не найден."
    if resource == "coins":
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    else:
        col = f"ore_{resource}"
        cur.execute(f"UPDATE users SET {col} = {col} + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()
    return True, f"Выдано {amount} игроку {user_id}."


# --- ПРОВЕРКА ПОДПИСИ TELEGRAM (Mini App) ---
def verify_init_data(init_data: str):
    """Возвращает user_id, если подпись Telegram верна, иначе None."""
    if not init_data or "ВСТАВЬ" in BOT_TOKEN:
        return None
    try:
        raw_pairs = init_data.split("&")
        hash_value = None
        check_parts = []
        for pair in raw_pairs:
            if pair.startswith("hash="):
                hash_value = pair[5:]
            else:
                check_parts.append(pair)
        if not hash_value:
            return None
        check_parts.sort()
        data_check_string = "\n".join(check_parts)
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, hash_value):
            return None
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        user = json.loads(parsed.get("user", "{}"))
        return int(user["id"])
    except Exception:
        return None


# --- РОЛИ И ДОСТУП ---
def current_role():
    tg_id = session.get("tg_id")
    if tg_id is not None:
        return ("admin" if tg_id in ADMIN_IDS else "player"), tg_id
    if session.get("logged_in"):
        return "admin", None
    return None, None


def require_admin(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        role, _ = current_role()
        if role != "admin":
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


# --- ШАБЛОНЫ ---
SHELL_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Панель шахты</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;display:flex;justify-content:center;padding-top:80px}
a{color:#8ab}</style>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
</head><body>
<div id="content"><p>Загрузка...</p></div>
<script>
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg && tg.initData && tg.initData.length > 0) {
    tg.ready();
    location.replace("/tg_auth?init=" + encodeURIComponent(tg.initData));
  } else {
    document.getElementById("content").innerHTML =
      "<p>Это мини-приложение для Telegram.</p>" +
      "<p>Открой бота и нажми кнопку в строке ввода,</p>" +
      "<p>или <a href='/login'>войти по паролю</a>.</p>";
  }
</script>
</body></html>"""

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

PANEL_PAGE = """<!doctype html><html><head><meta charset="utf-8">
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
<h2>⚙️ Панель шахты</h2>

<div class="box">
<h3 style="margin-top:0">🎁 Выдать игроку</h3>
<form method="post" action="/give">
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
<form method="post" action="/reset" onsubmit="return confirm('Точно сбросить баланс?')">
ID игрока: <input name="user_id" placeholder="ID игрока"><br>
<button>Сбросить баланс</button>
</form>
{% if reset_msg %}<p class="msg">{{ reset_msg }}</p>{% endif %}
{% if reset_err %}<p class="msg-err">{{ reset_err }}</p>{% endif %}
</div>

<form method="post" action="/save">
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
<td>🪨{{ p[5] }} ⚪{{ p[6] }} 🟤{{ p[7] }} 🟡{{ p[8] }}</td>
</tr>{% endfor %}</table>
<p><a href="/logout" style="color:#8ab">Выйти</a></p>
</body></html>"""

PLAYER_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Мой профиль</title><style>
body{font-family:sans-serif;background:#1e1e2e;color:#eee;max-width:520px;margin:30px auto;padding:0 15px}
.box{background:#2b2b3d;padding:15px 20px;border-radius:10px;margin-top:15px}
code{color:#8ab}</style></head><body>
<h2>⛏ Мой профиль</h2>
<div class="box">
<b>{{ username }}</b><br><br>
💰 Баланс: {{ balance }} монет<br>
🏅 Уровень: {{ level }}<br>
📈 Опыт: {{ xp }} / {{ needed }} до следующего<br>
⛏ Кирка: {{ pickaxe }}<br>
🎒 Рюкзак: {{ backpack }}
</div>
<p><a href="/logout" style="color:#8ab">Выйти</a></p>
</body></html>"""


def render_panel(settings, prices, players, give_msg, give_err, reset_msg, reset_err):
    return render_template_string(
        PANEL_PAGE, settings=settings, prices=prices, players=players,
        names=ORE_NAMES, picks=PICK_NAMES,
        give_msg=give_msg, give_err=give_err,
        reset_msg=reset_msg, reset_err=reset_err,
    )


# --- МАРШРУТЫ ---
@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/")
def index():
    role, tg_id = current_role()
    if role == "admin":
        settings, prices, players = load_all()
        return render_panel(settings, prices, players, "", "", "", "")
    if role == "player":
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT username, balance, xp, level, pickaxe_key, ore_stone, ore_iron, ore_copper, ore_gold FROM users WHERE user_id = ?", (tg_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            backpack = ", ".join(
                f"{ORE_ICONS[k]} {row[5 + i]}" for i, k in enumerate(["stone", "iron", "copper", "gold"]) if row[5 + i] > 0
            ) or "пусто"
            needed = (row[3]) * 100
            return render_template_string(
                PLAYER_PAGE, username=row[0], balance=row[1], xp=row[2],
                level=row[3], needed=needed, pickaxe=PICK_NAMES.get(row[4], row[4]),
                backpack=backpack,
            )
    return render_template_string(SHELL_PAGE)


@app.route("/tg_auth")
def tg_auth():
    init_data = request.args.get("init", "")
    tg_id = verify_init_data(init_data)
    if tg_id is None:
        return "Ошибка авторизации: данные не от Telegram. Открой панель через кнопку в боте.", 403
    session["tg_id"] = tg_id
    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if not PANEL_PASSWORD:
        return "Панель не настроена: задай переменную PANEL_PASSWORD перед запуском", 500
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Неверный пароль"
    return render_template_string(LOGIN_PAGE, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/give", methods=["POST"])
@require_admin
def give():
    try:
        user_id = int(request.form.get("user_id", ""))
        amount = int(request.form.get("amount", ""))
    except ValueError:
        return redirect(url_for("index"))
    resource = request.form.get("resource", "coins")
    if resource != "coins" and resource not in ORE_NAMES:
        resource = "coins"
    ok, msg = do_give(user_id, resource, amount)
    settings, prices, players = load_all()
    return render_panel(settings, prices, players, msg if ok else "", "" if ok else msg, "", "")


@app.route("/reset", methods=["POST"])
@require_admin
def reset():
    try:
        user_id = int(request.form.get("user_id", ""))
    except ValueError:
        return redirect(url_for("index"))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    settings, prices, players = load_all()
    return render_panel(settings, prices, players, "", "", f"Баланс игрока {user_id} сброшен до 0.", "")


@app.route("/save", methods=["POST"])
@require_admin
def save():
    conn = get_conn()
    cur = conn.cursor()
    for key in DEFAULT_SETTINGS:
        value = request.form.get(key)
        if value is not None:
            cur.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    for ore_key in DEFAULT_PRICES:
        value = request.form.get(f"price_{ore_key}")
        if value is not None:
            try:
                cur.execute("UPDATE prices SET price = ? WHERE ore_key = ?", (int(value), ore_key))
            except ValueError:
                pass
    conn.commit()
    conn.close()
    settings, prices, players = load_all()
    return render_panel(settings, prices, players, "Настройки сохранены ✅", "", "", "")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
