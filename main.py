import os, threading, asyncio
import bot
from web_panel import app

port = int(os.getenv("PORT", 8000))

threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=port),
    daemon=True,
).start()

asyncio.run(bot.main())
