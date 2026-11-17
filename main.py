import asyncio

from bot import bot, dp
from web_panel import start_web

async def main():
    # Бот и веб-панель работают в одном процессе
    await asyncio.gather(
        dp.start_polling(bot),
        start_web(),
    )

if name == "main":
    asyncio.run(main())
