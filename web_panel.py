import os
import secrets
import sqlite3

from flask import Flask, redirect, render_template_string, request, session, url_for

DB_NAME = "bot_db.sqlite"
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

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
DEFAULT_SETTINGS = {"mine_cooldown": "3", "bonus_amount": "5000", "bonus_hours": "12"}
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
    cur.execute("""SELECT username, balance, level, pickaxe_key,
                          ore_stone, ore_iron, ore_copper, ore_gold
                   FROM users ORDER BY balance DESC""")
    players = cur.fetchall()
    conn.close()
    return settings, prices, players

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
body{font-family:sans-serif;background:#1e1e2e;color:#eee;max-width:760px;margin:30px auto;padding:0 15px}
input{padding:6px;width:110px}button{padding:8px 20px;margin-top:12px}
table{border-collapse:collapse;margin-top:15px;font-size:14px}td,th{border:1px solid #555;padding:6px 12px}
h3{margin-top:25px}</style></head><body>
<h2>⚙️ Панель шахты</h2>
<form method="post" action="/save">
<h3>Настройки</h3>
Кулдаун накопания (сек): <input name="mine_cooldown" value="{{ settings.mine_cooldown }}"><br>
Бонус (монет): <input name="bonus_amount" value="{{ settings.bonus_amount }}"><br>
Бонус раз в (часов): <input name="bonus_hours" value="{{ settings.bonus_hours }}"><br>
<h3>Цены руды</h3>
{% for key, price in prices.items() %}{{ names[key] }}: <input name="price_{{ key }}" value="{{ price }}"><br>{% endfor %}
<button>💾 Сохранить</button>
</form>
<h3>Игроки</h3>
<table><tr><th>Игрок</th><th>Монеты</th><th>Уровень</th><th>Кирка</th><th>Рюкзак</th></tr>
{% for p in players %}<tr>
<td>{{ p[0] }}</td><td>{{ p[1] }}</td><td>{{ p[2] }}</td><td>{{ picks[p[3]] }}</td>
<td>🪨{{ p[4] }} ⚙️{{ p[5] }} 🥉{{ p[6] }} 💎{{ p[7] }}</td>
</tr>{% endfor %}</table>
<p><a href="/logout" style="color:#8ab">Выйти</a></p>
</body></html>"""

@app.route("/healthz")
def healthz():
    return "ok"

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if not PANEL_PASSWORD:
        return "Панель не настроена: задай переменную PANEL_PASSWORD в настройках Render", 500
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Неверный пароль"
    return render_template_string(LOGIN_PAGE, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    settings, prices, players = load_all()
    return render_template_string(
        PANEL_PAGE, settings=settings, prices=prices, players=players,
        names=ORE_NAMES, picks=PICK_NAMES,
    )

@app.route("/save", methods=["POST"])
def save():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    conn = get_conn()
    cur = conn.cursor()
    for key in DEFAULT_SETTINGS:
        val = request.form.get(key)
        if val is not None and val.isdigit():
            cur.execute("UPDATE settings SET value = ? WHERE key = ?", (val, key))
    for key in DEFAULT_PRICES:
        val = request.form.get(f"price_{key}")
        if val is not None and val.isdigit():
            cur.execute("UPDATE prices SET price = ? WHERE ore_key = ?", (int(val), key))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))
