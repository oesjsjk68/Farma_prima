import os, threading, asyncio
import bot                      # это твой bot.py
from web_panel import app       # это твой web_panel.py

# Render сам задаст переменную PORT, если её нет — будет 8080
port = int(os.getenv("PORT", 8080))

# Запускаем панель в отдельном потоке (чтобы она не блокировала бота)
threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=port, debug=False),
    daemon=True,
).start()

# Запускаем бота (он работает на asyncio)
asyncio.run(bot.main())
