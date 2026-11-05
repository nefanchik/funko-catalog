"""Одноразовий вхід у Telegram для sync.py.

Запускається на вашому комп'ютері:  py login.py
Попросить api_id / api_hash (з https://my.telegram.org), номер телефону і код з Telegram.
Наприкінці покаже рядок сесії та id ваших каналів — їх треба вставити в GitHub Secrets.

УВАГА: рядок сесії дає повний доступ до акаунта. Нікому його не пересилайте
і не зберігайте у файлах репозиторію — тільки в GitHub Secrets.
"""
import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(input("api_id: ").strip())
    api_hash = input("api_hash: ").strip()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()

    print("\nВаші канали (TG_CHANNEL = @username або id):")
    async for d in client.iter_dialogs():
        if d.is_channel and not d.is_group:
            user = getattr(d.entity, "username", None)
            print(f"  {d.name}:  {'@' + user if user else d.id}")

    print("\nTG_SESSION (скопіюйте весь рядок):\n")
    print(client.session.save())
    await client.disconnect()


asyncio.run(main())
