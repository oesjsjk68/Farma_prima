import os
import asyncio
import random
import sqlite3
import secrets
from datetime import datetime, timedelta

from aiohttp import web

# ================= НАСТРОЙКИ =================
PORT = int(os.getenv("PORT", 8080))
ROULETTE_COOLDOWN_SEC = 30
ROULETTE_MIN_LEVEL = 20
ROULETTE_MIN_BET = 10
ROULETTE_MAX_BET = 100000

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(SCRIPT_DIR, "bot_db.sqlite")

ORES = {
    "stone":  {"name": "\U0001FAA8 Камень",        "price": 2,  "xp": 2},
    "iron":   {"name": "\u26AA Железная руда",     "price": 8,  "xp": 5},
    "copper": {"name": "\U0001F7E4 Медная руда",   "price": 20, "xp": 10},
    "gold":   {"name": "\U0001F7E1 Золотая руда",  "price": 60000, "xp": 25},
}
ORE_KEYS = ["stone", "iron", "copper", "gold"]

PICKAXES = [
    {"key": "wood",    "name": "\U0001FAAB Деревянная", "power": 0,  "price": 0,       "level": 1},
    {"key": "stone",   "name": "\u2692\uFE0F Каменная", "power": 3,  "price": 5000,    "level": 10},
    {"key": "iron",    "name": "\u2692\uFE0F Железная", "power": 10, "price": 250000,  "level": 20},
    {"key": "gold",    "name": "\u2692\uFE0F Золотая",  "power": 25, "price": 1000000, "level": 35},
    {"key": "diamond", "name": "\u2692\uFE0F Алмазная", "power": 50, "price": 5000000, "level": 50},
]
PICKAXE_BY_KEY = {p["key"]: p for p in PICKAXES}

ROULETTE_SECTORS = [
    {"name": "\U0001F4A5 Джекпот x5!",        "chance": 0.02, "mult": 5.0},
    {"name": "\U0001F525 Крупный выигрыш x3", "chance": 0.08, "mult": 3.0},
    {"name": "\u2705 Выигрыш x2",             "chance": 0.20, "mult": 2.0},
    {"name": "\u2796 Возврат ставки",         "chance": 0.15, "mult": 1.0},
    {"name": "\u274C Проигрыш",               "chance": 0.55, "mult": 0.0},
]

tokens = {}          # token -> user_id
roulette_cd = {}     # token -> last spin ts

def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    return conn

def xp_needed_for_next_level(level):
    return level * 100

def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "user_id": row[0], "username": row[1], "balance": row[2],
        "xp": row[3], "level": row[4], "pickaxe_key": row[5],
        "last_mine_at": row[6], "last_bonus_at": row[7],
        "ore_stone": row[8], "ore_iron": row[9], "ore_copper": row[10], "ore_gold": row[11],
    }

def update_user(user_id, **kwargs):
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [user_id]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

def get_prices():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT ore_key, price FROM prices")
    result = dict(cur.fetchall())
    conn.close()
    return result

def can_mine(user):
    if not user["last_mine_at"]:
        return True
    last = datetime.fromisoformat(user["last_mine_at"])
    return datetime.now() >= last + timedelta(seconds=3)

def mine_seconds_left(user):
    last = datetime.fromisoformat(user["last_mine_at"])
    end = last + timedelta(seconds=3)
    return max(0, int((end - datetime.now()).total_seconds()))

def can_bonus(user):
    if not user["last_bonus_at"]:
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
    cur = conn.cursor()
    cur.execute("DELETE FROM web_codes WHERE code = ?", (code,))
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
    backpack = [{"key": k, "name": ORES[k]["name"], "count": user[f"ore_{k}"],
                 "price": prices.get(k, ORES[k]["price"])} for k in ORE_KEYS]
    total_bag = sum(x["count"] * x["price"] for x in backpack)
    needed = xp_needed_for_next_level(user["level"])
    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
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
    return api_json({
        "ok": True,
        "username": user["username"],
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
    })

async def api_mine(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    if not can_mine(user):
        return api_json({"ok": False, "error": f"Подожди ещё {mine_seconds_left(user)} сек."}, 429)
    pick = PICKAXE_BY_KEY[user["pickaxe_key"]]
    stone = random.randint(2, 4) + pick["power"] // 10 + user["level"] - 1
    iron = random.randint(1, 2) if random.random() < 0.2 + pick["power"] / 200 + (user["level"] - 1) / 100 else 0
    copper = random.randint(1, 2) if random.random() < 0.1 + pick["power"] / 400 + (user["level"] - 1) / 200 else 0
    gold = 1 if random.random() < 0.05 + pick["power"] / 800 + (user["level"] - 1) / 400 else 0
    total_xp = (stone * ORES["stone"]["xp"] + iron * ORES["iron"]["xp"]
                + copper * ORES["copper"]["xp"] + gold * ORES["gold"]["xp"])
    update_user(user["user_id"],
                ore_stone=user["ore_stone"] + stone, ore_iron=user["ore_iron"] + iron,
                ore_copper=user["ore_copper"] + copper, ore_gold=user["ore_gold"] + gold,
                last_mine_at=datetime.now().isoformat())
    new_level, levelups = add_xp(user["user_id"], user, total_xp)
    got = []
    for k, c in zip(ORE_KEYS, [stone, iron, copper, gold]):
        if c > 0:
            got.append({"name": ORES[k]["name"], "count": c})
    return api_json({"ok": True, "got": got, "xp": total_xp,
                     "levelup": levelups, "level": new_level})

async def api_sell(request):
    user, token = auth_user(request)
    if not user:
        return api_json({"ok": False, "error": "unauthorized"}, 401)
    prices = get_prices()
    total = 0
    lines = []
    for k in ORE_KEYS:
        cnt = user[f"ore_{k}"]
        if cnt > 0:
            money = cnt * prices.get(k, ORES[k]["price"])
            lines.append(f"{ORES[k]['name']} \u00D7 {cnt} = {money}")
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
    if keys.index(wanted["key"]) != keys.index(user["pickaxe_key"]) + 1:
        return api_json({"ok": False, "error": "Покупай по порядку"})
    if user["level"] < wanted["level"]:
        return api_json({"ok": False, "error": f"Нужен уровень {wanted['level']}"})
    if user["balance"] < wanted["price"]:
        return api_json({"ok": False, "error": f"Нужно {wanted['price']}, у тебя {user['balance']}"})
    update_user(user["user_id"], balance=user["balance"] - wanted["price"],
                pickaxe_key=wanted["key"])
    return api_json({"ok": True, "msg": f"Куплена кирка: {wanted['name']}!"})

# ================= HTML =================

PAGE = r"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Шахта</title>
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
 background:var(--card);display:flex;border-radius:18px 18px 0 0}
nav button{flex:1;background:none;border:none;color:var(--mut);padding:12px 0 14px;font-size:20px;cursor:pointer}
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
<header><div class="logo">prime</div><div class="chip" id="bal">\U0001F4B0 0</div><div class="chip" id="lvl">\U0001F3C5 1</div></header>
<main>
<div id="login" class="center" style="padding-top:80px">
 <div style="font-size:40px">\u26CF\uFE0F</div>
 <h2>Вход в шахту</h2>
 <p class="mut">Напиши боту <b>/код</b> и введи код здесь</p>
 <input id="code" placeholder="Код из бота" style="text-align:center">
 <button class="act" onclick="login()">Войти</button>
</div>
<div id="app" style="display:none">
 <div class="screen on" id="s-home">
  <div class="center">
   <div class="bar" style="max-width:280px"><div id="xpbar"></div></div>
   <div class="mut" id="xptext"></div>
   <button id="mineBtn" onclick="mine()">\u26CF\uFE0F<br>Копать</button>
   <div class="mut" id="minewait"></div>
  </div>
 </div>
 <div class="screen" id="s-bag">
  <h3>\U0001F392 Инвентарь</h3>
  <div class="card" id="bagList"></div>
  <button class="act" style="width:100%" onclick="sell()">\U0001F4B0 Продать всё</button>
 </div>
 <div class="screen" id="s-shop"><h3>\U0001F6D2 Магазин кирок</h3><div id="shopList"></div></div>
 <div class="screen" id="s-top">
  <h3>\U0001F3C6 Богачи</h3><div class="card" id="topRich"></div>
  <h3>\U0001F3C6 Уровни</h3><div class="card" id="topLvl"></div>
 </div>
 <div class="screen" id="s-prof">
  <div class="card" id="profCard"></div>
  <h3>\U0001F381 Бонус</h3>
  <div class="card"><button class="act" style="width:100%" id="bonusBtn" onclick="bonus()">Забрать бонус</button></div>
  <h3>\U0001F3B2 Рулетка</h3>
  <div class="card">
   <div id="roulInfo" class="mut"></div>
   <input id="bet" placeholder="Ставка, напр. 100" style="margin-top:8px;text-align:center">
   <button class="act" style="width:100%;margin-top:8px" onclick="spin()">Крутить</button>
  </div>
 </div>
</div>
</main>
<nav id="nav" style="display:none">
 <button class="on" onclick="tab(0,this)">\u26CF\uFE0F<br><small>Добыча</small></button>
 <button onclick="tab(1,this)">\U0001F392<br><small>Рюкзак</small></button>
 <button onclick="tab(2,this)">\U0001F6D2<br><small>Магазин</small></button>
 <button onclick="tab(3,this)">\U0001F3C6<br><small>Топ</small></button>
 <button onclick="tab(4,this)">\U0001F464<br><small>Профиль</small></button>
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
 if(!d.ok)return;window.D=d;$("bal").textContent="\U0001F4B0 "+d.balance.toLocaleString("ru");
 $("lvl").textContent="\U0001F3C5 "+d.level;$("login").style.display="none";$("app").style.display="block";$("nav").style.display="flex";
 const p=Math.min(100,Math.round(d.xp/d.xp_needed*100));$("xpbar").style.width=p+"%";
 $("xptext").textContent=d.xp+" / "+d.xp_needed+" опыта до ур. "+(d.level+1);
 $("minewait").textContent=d.mine_ready?"Руда ждёт!":"Перезарядка: "+d.mine_wait+" сек";
 $("mineBtn").disabled=!d.mine_ready;
 $("bagList").innerHTML=d.backpack.map(x=>x.count>0?`<div class="row"><span>${x.name} \u00D7 ${x.count}</span><span class="mut">${(x.count*x.price).toLocaleString("ru")} \u20BF</span></div>`:"").join("")||"<div class='mut'>Пусто</div>";
 if(d.bag_value>0)$("bagList").innerHTML+=`<div class="row"><b>Итого</b><b>${d.bag_value.toLocaleString("ru")} \u20BF</b></div>`;
 $("shopList").innerHTML=d.shop.filter(x=>x.price>0).map(x=>{const can=d.level>=x.level&&d.balance>=x.price;return `<div class="card"><div class="row"><b>${x.name}</b><span class="mut">${x.power} силы</span></div><div class="row"><span>${x.price.toLocaleString("ru")} \u20BF</span><span class="mut">ур. ${x.level}</span></div><button class="${can?"act":"ghost"}" style="width:100%;margin-top:8px" onclick="buy('${x.key}')">${can?"Купить":"Недоступно"}</button></div>`}).join("");
 const med=["\U0001F947","\U0001F948","\U0001F949"];
 $("topRich").innerHTML=d.top_rich.map((x,i)=>`<div class="row"><span>${med[i]||"\u25AB\uFE0F"} ${x[0]}</span><b>${x[1].toLocaleString("ru")}</b></div>`).join("");
 $("topLvl").innerHTML=d.top_level.map((x,i)=>`<div class="row"><span>${med[i]||"\u25AB\uFE0F"} ${x[0]}</span><b>ур. ${x[1]}</b></div>`).join("");
 $("profCard").innerHTML=`<div class="row"><span>\U0001F464 Игрок</span><b>${d.username}</b></div><div class="row"><span>\u2692\uFE0F Кирка</span><b>${d.pickaxe}</b></div><div class="row"><span>\U0001F3C5 Уровень</span><b>${d.level}</b></div><div class="row"><span>\U0001F4B0 Баланс</span><b>${d.balance.toLocaleString("ru")} \u20BF</b></div>`;
 $("bonusBtn").textContent=d.bonus_ready?"Забрать бонус":"Через "+d.bonus_left;
 $("bonusBtn").className=d.bonus_ready?"act":"ghost";
 $("roulInfo").innerHTML=d.roulette_open?"Ставка: 10\u2013100 \u20BF \u2022 2% джекпот x5, 8% x3, 20% x2, 15% возврат":"\U0001F512 Откроется с "+d.roulette_min_level;
}
async function mine(){const d=await api("mine");if(!d.ok){toast(d.error,false);refresh();return;}
 toast(d.got.map(x=>x.name+" \u00D7 "+x.count).join(", ")+" \u2022 +"+d.xp+" опыта"+(d.levelup?" \U0001F389 Уровень "+d.level+"!":""));refresh();}
async function sell(){const d=await api("sell");if(!d.ok){toast(d.error,false);return;}toast("Продано на "+d.total.toLocaleString("ru")+" \u20BF!");refresh();}
async function bonus(){const d=await api("bonus");if(!d.ok){toast(d.error,false);return;}toast("\U0001F381 +"+d.amount.toLocaleString("ru")+" \u20BF!");refresh();}
async function spin(){const d=await api("roulette",{bet:$("bet").value.trim()||null});if(d.prompt){toast("Напиши сумму ставки");return;}
 if(!d.ok){toast(d.error,false);return;}toast(d.sector+(d.delta>0?" \u2022 +"+d.delta:d.delta===0?" \u2022 возврат":" \u2022 -"+d.bet),d.delta>=0);refresh();}
async function buy(k){const d=await api("buy",{key:k});toast(d.ok?d.msg:d.error,!!d.ok);refresh();}
function tab(i,btn){document.querySelectorAll(".screen").forEach((s,j)=>s.classList.toggle("on",j===i));
 document.querySelectorAll("nav button").forEach(b=>b.classList.remove("on"));btn.classList.add("on");}
refresh();
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
    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/mine", api_mine)
    app.router.add_post("/api/sell", api_sell)
    app.router.add_post("/api/bonus", api_bonus)
    app.router.add_post("/api/roulette", api_roulette)
    app.router.add_post("/api/buy", api_buy)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web panel on port {PORT}")

async def main():
    await start_web()
    await asyncio.Event().wait()  # держим сервер живым навсегда

if __name__ == "__main__":
    asyncio.run(main())
