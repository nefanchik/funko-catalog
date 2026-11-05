"""Одноразовий вхід у Telegram для sync.py — через QR-код.

Запускається на вашому комп'ютері:  py login.py
Попросить api_id / api_hash (з https://my.telegram.org), потім відкриє QR-код у браузері.
Скануйте його телефоном: Telegram → Налаштування → Пристрої → Підключити пристрій.
Наприкінці покаже id ваших каналів і рядок сесії — їх треба вставити в GitHub Secrets.

УВАГА: рядок сесії дає повний доступ до акаунта. Нікому його не пересилайте
і не зберігайте у файлах репозиторію — тільки в GitHub Secrets.
"""
import asyncio
import getpass
import os
import tempfile

import qrcode
import qrcode.image.svg
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

QR_FILE = os.path.join(tempfile.gettempdir(), "telegram_login_qr.html")


def show_qr(url):
    svg = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12).to_string(encoding="unicode")
    with open(QR_FILE, "w", encoding="utf-8") as f:
        f.write(
            "<meta charset='utf-8'><style>svg{width:320px;height:320px;display:block}</style>"
            "<body style='font:18px sans-serif;text-align:center;padding:30px'>"
            "<h2>Скануйте телефоном</h2>"
            "<p>Telegram → Налаштування → Пристрої → <b>Підключити пристрій</b></p>"
            f"<div style='display:inline-block;padding:20px;background:#fff'>{svg}</div>"
            "<p style='color:#888'>Якщо не встигли — програма за пів хвилини відкриє новий QR-код у новій вкладці</p>"
        )
    os.startfile(QR_FILE)


async def main():
    api_id = int(input("api_id: ").strip())
    api_hash = input("api_hash: ").strip()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()

    qr = await client.qr_login()
    show_qr(qr.url)
    print("\nУ браузері відкрився QR-код. Скануйте його телефоном:")
    print("Telegram -> Налаштування -> Пристрої -> Підключити пристрій\n")
    while True:
        try:
            await qr.wait(timeout=25)
            break
        except asyncio.TimeoutError:
            await qr.recreate()
            show_qr(qr.url)
            print("Старий QR-код застарів — у браузері відкрився новий")
        except SessionPasswordNeededError:
            await client.sign_in(password=getpass.getpass("Пароль двоетапної перевірки (букви не видно): "))
            break
    os.remove(QR_FILE)

    me = await client.get_me()
    print(f"\nУвійшли як {me.first_name}")
    print("\nВаші канали (TG_CHANNEL = @username або число):")
    async for d in client.iter_dialogs():
        if d.is_channel and not d.is_group:
            user = getattr(d.entity, "username", None)
            print(f"  {d.name}:  {'@' + user if user else d.id}")

    print("\nTG_SESSION (скопіюйте весь рядок):\n")
    print(client.session.save())
    await client.disconnect()


asyncio.run(main())
