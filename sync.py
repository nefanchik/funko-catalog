"""Синхронізує каталог з Telegram-каналом.

Читає всі пости каналу, додає нові фігурки, прибирає видалені й оновлює змінені
(ціна, опис). Нові фото завантажує, фото видалених постів стирає.

Налаштування — змінні середовища (на GitHub вони задаються як Secrets):
    TG_API_ID, TG_API_HASH  — з https://my.telegram.org
    TG_SESSION              — рядок сесії з login.py
    TG_CHANNEL              — @username каналу або його числовий id
"""
import asyncio
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from telethon import TelegramClient
from telethon.helpers import add_surrogate, del_surrogate
from telethon.sessions import StringSession
from telethon.tl import types

HERE = Path(__file__).resolve().parent
PHOTOS = HERE / "photos"
DATA = HERE / "data.js"


def clean(s):
    # Прибирає емодзі та пробіли на краях: "🧬AMERICA CHAVEZ #1002 " -> "AMERICA CHAVEZ #1002"
    s = s.strip()
    while s and (unicodedata.category(s[0]) in ("So", "Sk", "Cf", "Mn") or s[0] in "️‍"):
        s = s[1:].lstrip()
    while s and (unicodedata.category(s[-1]) in ("So", "Sk", "Cf", "Mn") or s[-1] in "️‍"):
        s = s[:-1].rstrip()
    return s


def entities_text(text, entities):
    t = add_surrogate(text)
    return [(e, del_surrogate(t[e.offset:e.offset + e.length])) for e in entities or []]


def parse_post(text, entities):
    """Розбирає текст поста. Повертає dict або None, якщо це не товар."""
    if "ПРИДБАТИ" not in text:
        return None
    ents = entities_text(text, entities)
    of = lambda cls: [s for e, s in ents if isinstance(e, cls)]

    tags = [s.lstrip("#").lower() for s in of(types.MessageEntityHashtag)]
    tags = [t for t in tags if re.search(r"[^\d]", t)]
    series = next((clean(s) for s in of(types.MessageEntityItalic) if clean(s)), "")
    names = [clean(s) for s in of(types.MessageEntityBold)
             if re.search(r"[A-Za-zА-Яа-яІіЇїЄє]", s) and "грн" not in s]
    name = names[0] if names else ""
    price = re.search(r"(\d[\d\s]*)\s*грн", text)
    links = {s.strip(): e.url for e, s in ents if isinstance(e, types.MessageEntityTextUrl)}
    link = lambda word: next((u for s, u in links.items() if word in s), "")
    quote = of(types.MessageEntityBlockquote)
    num = re.search(r"#\s*(\d+)\s*$", name)
    return {
        "tags": tags,
        "series": series,
        "name": re.sub(r"\s*#\s*\d+\s*$", "", name).strip(),
        "num": num.group(1) if num else "",
        "price": int(re.sub(r"\s", "", price.group(1))) if price else None,
        "buy": link("ПРИДБАТИ"),
        "extra": link("ДОДАТКОВІ"),
        "desc": quote[0].strip() if quote else "",
    }


def pick_thumb(photo):
    # Найбільший розмір, не ширший за 800px — для сітки цього досить
    sizes = [s for s in photo.sizes if isinstance(s, (types.PhotoSize, types.PhotoSizeProgressive))]
    small = [s for s in sizes if max(s.w, s.h) <= 800]
    return max(small or sizes, key=lambda s: s.w * s.h)


async def resolve_channel(client, ref):
    ref = ref.strip().lstrip("@")
    if re.fullmatch(r"-?\d+", ref):
        want = int(ref)
        async for d in client.iter_dialogs():
            if d.is_channel and want in (d.id, d.entity.id):
                return d.entity
        sys.exit(f"Канал {ref} не знайдено серед ваших чатів")
    return await client.get_entity(ref)


async def main():
    client = TelegramClient(StringSession(os.environ["TG_SESSION"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Сесія недійсна — запустіть login.py ще раз")
    channel = await resolve_channel(client, os.environ["TG_CHANNEL"])

    # Альбом = кілька повідомлень з однаковим grouped_id
    groups = {}
    async for m in client.iter_messages(channel):
        if not isinstance(m, types.Message):
            continue
        key = ("g", m.grouped_id) if m.grouped_id else ("m", m.id)
        groups.setdefault(key, []).append(m)

    items = []
    for msgs in groups.values():
        msgs.sort(key=lambda m: m.id)
        texted = next((m for m in msgs if m.message and "ПРИДБАТИ" in m.message), None)
        if not texted:
            continue
        item = parse_post(texted.message, texted.entities)
        photos = [m for m in msgs if isinstance(m.media, types.MessageMediaPhoto)]
        if not item or not photos or item["price"] is None:
            continue
        item = {"id": msgs[0].id, "date": texted.date.strftime("%Y-%m-%d"), **item, "photos": []}
        for m in photos:
            full, thumb = PHOTOS / f"{m.id}.jpg", PHOTOS / f"{m.id}_thumb.jpg"
            if not full.exists():
                await client.download_media(m, file=str(full))
            if not thumb.exists():
                await client.download_media(m, file=str(thumb), thumb=pick_thumb(m.photo))
            item["photos"].append({"full": f"photos/{full.name}", "thumb": f"photos/{thumb.name}"})
        items.append(item)
    await client.disconnect()
    items.sort(key=lambda x: -x["id"])

    # Захист: якщо раптом прийшло набагато менше постів (збій Telegram), нічого не стираємо
    old = []
    if DATA.exists():
        old = json.loads(DATA.read_text(encoding="utf-8").removeprefix("window.CATALOG=").rstrip().rstrip(";"))
    if old and len(items) < len(old) * 0.5 and not os.environ.get("FORCE"):
        sys.exit(f"Отримано лише {len(items)} позицій замість {len(old)} — зупиняюсь про всяк випадок")

    used = {Path(p[k]).name for it in items for p in it["photos"] for k in ("full", "thumb")}
    for f in PHOTOS.glob("*.jpg"):
        if f.name not in used:
            f.unlink()

    old_ids, new_ids = {x["id"] for x in old}, {x["id"] for x in items}
    data = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    DATA.write_text(f"window.CATALOG={data};\n", encoding="utf-8")
    print(f"Позицій: {len(items)} (нових {len(new_ids - old_ids)}, прибрано {len(old_ids - new_ids)})")


if __name__ == "__main__":
    PHOTOS.mkdir(exist_ok=True)
    asyncio.run(main())
