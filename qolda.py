#!/usr/bin/env python3
"""Drive'ga emas, to'g'ridan-to'g'ri yuborilgan kitoblarni qo'shadi.

"qolda-yuklash" shoxobchasiga yukla.json va PDF fayllar qo'yiladi:
  [{"file": "kitoblar/x.pdf", "name": "Muallif - Kitob nomi.pdf",
    "category": "Tafsir", "description": ""}]
yoki o'chirish uchun: {"ochir": "<kitob id>"}
Natija qolda.json ga yoziladi; sync.py uni Drive kitoblari bilan birga katalogga qo'shadi.
"""
import datetime
import hashlib
import json
import os
import sys

os.environ.setdefault("DRIVE_FOLDER_ID", "")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync  # noqa: E402

QOLDA = os.path.join(sync.ROOT, "qolda.json")


def main(src):
    items = json.load(open(os.path.join(src, "yukla.json"), encoding="utf-8"))
    data = json.load(open(QOLDA, encoding="utf-8")) if os.path.exists(QOLDA) else {"books": []}
    books = {b["id"]: b for b in data["books"]}
    cat_order = {}
    if os.path.exists(sync.CATALOG):
        for b in json.load(open(sync.CATALOG, encoding="utf-8")).get("books", []):
            cat_order[b["category"]] = b.get("catOrder", 500)
    os.makedirs(sync.COVERS, exist_ok=True)

    for it in items:
        if "ochir" in it:
            bid = it["ochir"]
            if bid in books:
                sync.log("O'chirildi:", books[bid]["title"])
                sync.gh("release", "delete-asset", sync.RELEASE, bid + ".pdf", "-y", check=False)
                cf = os.path.join(sync.COVERS, bid + ".jpg")
                if os.path.exists(cf):
                    os.remove(cf)
                del books[bid]
            continue

        path = os.path.join(src, it["file"])
        with open(path, "rb") as fh:
            raw = fh.read()
        if not raw.startswith(b"%PDF-"):
            sync.log("PDF emas:", it["file"])
            continue
        digest = hashlib.sha256(raw).hexdigest()
        author, title = sync.parse_name(it["name"])
        title, lang = sync.split_script(title)
        cat = (it.get("category") or sync.UNCATEGORIZED).strip()
        bid = hashlib.sha1(("kutubxonamiz:qolda:" + digest).encode()).hexdigest()[:16]
        sync.log("Kitob:", title, "|", lang, "|", cat)

        sync.clean_pdf(path, title, author)
        pdf = os.path.join(os.path.dirname(path), bid + ".pdf")
        os.replace(path, pdf)
        sync.gh("release", "upload", sync.RELEASE, pdf, "--clobber")
        sync.log("  relizga yuklandi")

        cover_file = os.path.join(sync.COVERS, bid + ".jpg")
        cover_src = "pdf:" + digest[:12]
        try:
            if it.get("cover"):
                sync.make_cover(os.path.join(src, it["cover"]), cover_file, False)
                cover_src = "img:" + digest[:12]
            else:
                sync.make_cover(pdf, cover_file, True)
            sync.log("  muqova tayyor")
        except Exception as e:
            sync.log("  muqova yasalmadi:", e)
            cover_src = None

        books[bid] = {
            "id": bid,
            "title": title,
            "author": author,
            "category": cat,
            "catOrder": cat_order.get(cat, 999 if cat == sync.UNCATEGORIZED else 500),
            "url": sync.ASSET_URL + bid + ".pdf",
            "cover": (sync.RAW + "/covers/" + bid + ".jpg?v=" + (cover_src or "0")[-8:])
                     if os.path.exists(cover_file) else "",
            "size": os.path.getsize(pdf),
            "added": books.get(bid, {}).get("added")
                     or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "description": (it.get("description") or "").strip(),
            "lang": lang,
            "group": cat + "/" + sync.group_key(title),
            "md5": digest,
            "pv": sync.PROCESS_VERSION,
            "coverSrc": cover_src,
            "manba": "qolda",
        }

    data["books"] = sorted(books.values(), key=lambda b: b["added"], reverse=True)
    with open(QOLDA, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    sync.log(f"qolda.json: {len(books)} ta kitob")


def qayta():
    """Eski usulda tozalangan kitoblarni yangi tozalagich bilan qayta ishlaydi."""
    if not os.path.exists(QOLDA):
        return
    data = json.load(open(QOLDA, encoding="utf-8"))
    work = os.path.join(sync.ROOT, ".qayta")
    os.makedirs(work, exist_ok=True)
    changed = False
    for b in data["books"]:
        if b.get("pv", 0) >= sync.PROCESS_VERSION:
            continue
        sync.log("Qayta tozalash:", b["title"])
        sync.gh("release", "download", sync.RELEASE, "-p", b["id"] + ".pdf", "-D", work, "--clobber")
        pdf = os.path.join(work, b["id"] + ".pdf")
        sync.clean_pdf(pdf, b["title"], b["author"])
        sync.gh("release", "upload", sync.RELEASE, pdf, "--clobber")
        b["size"] = os.path.getsize(pdf)
        b["pv"] = sync.PROCESS_VERSION
        os.remove(pdf)
        changed = True
    if changed:
        with open(QOLDA, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
    import shutil
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    if sys.argv[1] == "--qayta":
        qayta()
    else:
        main(sys.argv[1])
