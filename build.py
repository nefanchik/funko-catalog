"""Збирає каталог з експорту Telegram-каналу.

Використання:
    py build.py                      # експорт лежить у батьківській папці
    py build.py "D:/ChatExport_..."  # або вкажіть шлях до нового експорту

Створює data.js і копіює потрібні фото в папку photos/ поруч зі скриптом.
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPORT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent


def strip(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse(text):
    groups, cur = [], None
    for b in re.split(r'<div class="message ', text)[1:]:
        if b.startswith("service"):
            continue
        mid = re.search(r'id="message(\d+)"', b)
        ts = re.search(r'class="pull_right date details" title="([^"]+)"', b)
        if not mid or not ts:
            continue
        body = re.search(r'<div class="text">\n?(.*?)\n\s*</div>', b, re.S)
        body = body.group(1) if body and "ПРИДБАТИ" in body.group(1) else None
        # Текст альбому стоїть на першому повідомленні, решта фото — "joined" з тим самим часом
        if body or cur is None or cur["ts"] != ts.group(1):
            cur = {"ts": ts.group(1), "ids": [], "photos": [], "text": body}
            groups.append(cur)
        cur["ids"].append(int(mid.group(1)))
        for full, thumb in re.findall(
            r'<a class="photo_wrap[^"]*" href="([^"]+)">\s*<img class="photo" src="([^"]+)"', b
        ):
            cur["photos"].append({"msg": int(mid.group(1)), "full": full, "thumb": thumb})

    items = []
    for g in groups:
        t = g["text"]
        if not t:
            continue
        strongs = [strip(s) for s in re.findall(r"<strong>(.*?)</strong>", t, re.S)]
        names = [s for s in strongs if re.search(r"[A-Za-zА-Яа-яІіЇїЄє]", s) and "грн" not in s]
        name = names[0] if names else ""
        price = re.search(r"(\d[\d\s]*)\s*грн", strip(t))
        extra = re.search(r'<a href="([^"]+)">ДОДАТКОВІ ФОТО</a>', t)
        buy = re.search(r'<a href="([^"]+)">ПРИДБАТИ</a>', t)
        em = re.search(r"<em>(.*?)</em>", t, re.S)
        quote = re.search(r"<blockquote>(.*?)</blockquote>", t, re.S)
        num = re.search(r"#\s*(\d+)\s*$", name)
        d = re.match(r"(\d\d)\.(\d\d)\.(\d{4})", g["ts"])
        items.append({
            "id": min(g["ids"]),
            "date": f"{d.group(3)}-{d.group(2)}-{d.group(1)}",
            "tags": [x.lower() for x in re.findall(r"ShowHashtag\(&quot;([^&]+)&quot;\)", t)],
            "series": strip(em.group(1)) if em else "",
            "name": re.sub(r"\s*#\s*\d+\s*$", "", name).strip(),
            "num": num.group(1) if num else "",
            "price": int(re.sub(r"\s", "", price.group(1))) if price else None,
            "buy": buy.group(1) if buy else "",
            "extra": extra.group(1) if extra else "",
            "desc": strip(re.sub(r"<br\s*/?>", "\n", quote.group(1))) if quote else "",
            "photos": g["photos"],
        })
    items.sort(key=lambda x: -x["id"])
    return items


def main():
    pages = sorted(EXPORT.glob("messages*.html"), key=lambda p: (len(p.name), p.name))
    if not pages:
        sys.exit(f"Не знайдено messages.html у {EXPORT}")
    items = parse("".join(p.read_text(encoding="utf-8") for p in pages))

    out = HERE / "photos"
    out.mkdir(exist_ok=True)
    for it in items:
        for ph in it["photos"]:
            # Ті самі імена файлів, що й у sync.py: <номер повідомлення>.jpg
            msg = ph.pop("msg")
            for k, name in (("full", f"{msg}.jpg"), ("thumb", f"{msg}_thumb.jpg")):
                src = EXPORT / ph[k]
                if src.exists() and not (out / name).exists():
                    shutil.copy2(src, out / name)
                ph[k] = "photos/" + name

    data = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    (HERE / "data.js").write_text(f"window.CATALOG={data};\n", encoding="utf-8")
    print(f"Готово: {len(items)} позицій -> data.js")


if __name__ == "__main__":
    main()
