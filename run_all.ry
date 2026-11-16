import os, threading, asyncio
import bot                      # твой bot.py
from web_panel import app

port = int(os.getenv("PORT", 8080))   # на Render возьмётся 10000, локально — 8080
threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=port),
    daemon=True,
).start()

asyncio.run(bot.main())
