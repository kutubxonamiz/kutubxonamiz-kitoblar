#!/usr/bin/env python3
"""Google Drive papkasidagi kitoblarni shu omborga ko'chiradi.

- PDF fayllar "kitoblar" relizi fayllari sifatida yuklanadi (GitHub CDN orqali
  millionlab yuklashni ko'taradi).
- Muqovalar covers/ papkasiga JPG qilib saqlanadi. PDF bilan bir xil nomli rasm
  bo'lsa o'sha olinadi, bo'lmasa PDFning birinchi betidan yasaladi.
- catalog.json ilova o'qiydigan ro'yxat. "app" bo'limiga tegilmaydi.

Drive'da: asosiy papka = "Umumiy" bo'limi, ichki papkalar = bo'limlar.
Fayl nomi: "Muallif - Kitob nomi.pdf".
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request

from news_sync import build_news, is_news_folder

FOLDER = os.environ["DRIVE_FOLDER_ID"]
SA_KEY = os.environ.get("DRIVE_SA_KEY", "").strip()   # robot hisob (papka yopiq)
KEY = os.environ.get("DRIVE_API_KEY", "").strip()      # eski usul (papka ochiq)
_TOKEN = None


def auth():
    """So'rovlar uchun: robot hisob tokeni yoki API kalit."""
    global _TOKEN
    if SA_KEY:
        if _TOKEN is None:
            from google.oauth2 import service_account
            import google.auth.transport.requests
            creds = service_account.Credentials.from_service_account_info(
                json.loads(SA_KEY), scopes=["https://www.googleapis.com/auth/drive.readonly"])
            creds.refresh(google.auth.transport.requests.Request())
            _TOKEN = creds.token
        return {"Authorization": "Bearer " + _TOKEN}, {}
    return {}, {"key": KEY}
REPO = os.environ["GITHUB_REPOSITORY"]
RELEASE = "kitoblar"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
ASSET_URL = f"https://github.com/{REPO}/releases/download/{RELEASE}/"
ROOT = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(ROOT, "catalog.json")
COVERS = os.path.join(ROOT, "covers")
UNCATEGORIZED = "Umumiy"
PROCESS_VERSION = 4  # oshirilsa, hamma PDF qayta ishlanadi


def pub_id(drive_id):
    """Drive raqamini ochiq joyda ko'rsatmaslik uchun: undan yasalgan tasodifiy ko'rinishdagi raqam."""
    return hashlib.sha1(("kutubxonamiz:" + drive_id).encode()).hexdigest()[:16]


def log(*a):
    print(*a, flush=True)


def drive(path, params):
    headers, extra = auth()
    url = "https://www.googleapis.com/drive/v3/" + path + "?" + urllib.parse.urlencode(dict(params, **extra))
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return json.load(r)


def list_folder(fid):
    out, token = [], None
    while True:
        p = {
            "q": f"'{fid}' in parents and trashed = false",
            "fields": "nextPageToken, files(id,name,mimeType,size,createdTime,modifiedTime,description,md5Checksum)",
            "pageSize": "1000",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if token:
            p["pageToken"] = token
        d = drive("files", p)
        out += d.get("files", [])
        token = d.get("nextPageToken")
        if not token:
            return out


def download(fid, dest):
    headers, extra = auth()
    url = (f"https://www.googleapis.com/drive/v3/files/{fid}?"
           + urllib.parse.urlencode(dict({"alt": "media"}, **extra)))
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=900) as r, \
            open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def clean_pdf(path, title, author):
    """PDF ichidagi yashirin ma'lumotlarni (kim yasagan, dastur raqamlari, rasmlardagi EXIF) olib tashlaydi."""
    try:
        from pdf_tozala import tozala
        tozala(path, path, title)  # muallif ham yozilmaydi
    except Exception as e:
        log("  metama'lumot tozalanmadi:", e)


def gh(*args, check=True):
    return subprocess.run(["gh", *args, "--repo", REPO], check=check,
                          capture_output=True, text=True)


def base(name):
    i = name.rfind(".")
    return (name[:i] if i > 0 else name).strip()


def parse_name(name):
    b = base(name).replace("_", " ").strip()
    if " - " in b:
        a, t = b.split(" - ", 1)
        return a.strip(), t.strip()
    return "", b


CYR_LETTERS = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳ")
SCRIPT_WORDS = {
    "lotin": "lotin", "lotincha": "lotin", "latin": "lotin", "лотин": "lotin", "лотинча": "lotin",
    "kirill": "kirill", "kirillcha": "kirill", "krill": "kirill", "cyrillic": "kirill",
    "кирилл": "kirill", "кириллча": "kirill",
}
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "s",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}


def split_script(title):
    """'Ilmga ishtiyoq (lotin)' -> ('Ilmga ishtiyoq', 'lotin')"""
    lang, out, found = "", [], False
    for w in re.split(r"[\s_]+", title):
        key = re.sub(r"[()\[\],.\-]", "", w).lower()
        if key in SCRIPT_WORDS:
            lang, found = SCRIPT_WORDS[key], True
            continue
        out.append(w)
    if found and out and re.fullmatch(r"\(?(19|20)\d\d\)?", out[-1]):
        out.pop()  # "..._lotin_2026" dagi yil
    clean = " ".join(out).strip(" -_()[]")
    if not lang:
        lang = "kirill" if any(ch in CYR_LETTERS for ch in title.lower()) else "lotin"
    return clean or title, lang


def group_key(title):
    """Lotin va kirill nomlarni bir xil kalitga keltiradi."""
    t = title.lower()
    out = []
    for i, ch in enumerate(t):
        if ch == "е" and (i == 0 or not t[i - 1].isalpha()):
            out.append("ye")
        else:
            out.append(TRANSLIT.get(ch, ch))
    k = re.sub(r"[^a-z0-9]", "", "".join(out))
    return k.replace("ye", "e").replace("ts", "s").replace("yo", "o")


def parse_category(name):
    """'1. Tafsir' -> ('Tafsir', 1). Raqamsiz bo'lsa tartib 500."""
    m = re.match(r"^\s*(\d+)\s*[.)\-:]\s*(.+)$", name)
    if m:
        return m.group(2).strip(), int(m.group(1))
    return name.strip(), 500


def make_cover(src, out_jpg, from_pdf):
    from PIL import Image
    tmp = None
    if from_pdf:
        tmp = out_jpg + ".page"
        subprocess.run(["pdftoppm", "-jpeg", "-f", "1", "-l", "1", "-scale-to", "900",
                        "-singlefile", src, tmp], check=True)
        src = tmp + ".jpg"
    im = Image.open(src).convert("RGB")
    im.thumbnail((600, 860))
    im.save(out_jpg, "JPEG", quality=85, optimize=True, progressive=True)
    if tmp and os.path.exists(tmp + ".jpg"):
        os.remove(tmp + ".jpg")


def main():
    old = {}
    catalog = {"books": []}
    if os.path.exists(CATALOG):
        catalog = json.load(open(CATALOG, encoding="utf-8"))
        old = {b["id"]: b for b in catalog.get("books", [])}

    log("Drive'ga ulanish:", "robot hisob (papka yopiq)" if SA_KEY else "API kalit (papka ochiq)")
    fresh_release = False
    if gh("release", "view", RELEASE, check=False).returncode != 0:
        gh("release", "create", RELEASE, "--prerelease", "--title", "Kitoblar",
           "--notes", "Kutubxonamiz ilovasi kitoblari. Avtomatik yangilanadi.")
        fresh_release = True  # yangi reliz bo'sh — hamma PDF qayta yuklanadi
        log("Reliz yaratildi:", RELEASE)

    # Drive'dagi hamma fayllar: (fayl, bo'lim)
    root = list_folder(FOLDER)
    entries = [(f, UNCATEGORIZED) for f in root]
    cat_order = {UNCATEGORIZED: 999}
    for folder in [f for f in root if f["mimeType"] == "application/vnd.google-apps.folder"
                   and not is_news_folder(f["name"])]:
        cname, corder = parse_category(folder["name"])
        cat_order[cname] = corder
        entries += [(f, cname) for f in list_folder(folder["id"])]

    images = {}
    for f, cat in entries:
        if f["mimeType"].startswith("image/"):
            images[(cat, base(f["name"]).lower())] = f

    books, work = [], tempfile.mkdtemp()
    for f, cat in entries:
        is_pdf = f["mimeType"] == "application/pdf" or f["name"].lower().endswith(".pdf")
        if not is_pdf:
            continue
        fid = f["id"]
        bid = pub_id(fid)
        author, title = parse_name(f["name"])
        title, lang = split_script(title)
        img = images.get((cat, base(f["name"]).lower()))
        pdf_md5 = f.get("md5Checksum", f.get("size", ""))
        cover_src = ("img:" + img.get("md5Checksum", img["id"])) if img else ("pdf:" + pdf_md5)
        prev = old.get(bid, {})
        pdf_path = None

        if fresh_release or prev.get("md5") != pdf_md5 or prev.get("pv") != PROCESS_VERSION:
            pdf_path = os.path.join(work, bid + ".pdf")
            log("Yuklanmoqda:", f["name"])
            download(fid, pdf_path)
            with open(pdf_path, "rb") as fh:
                if fh.read(5) != b"%PDF-":
                    log("  PDF emas, o'tkazib yuborildi")
                    continue
            clean_pdf(pdf_path, title, author)
            gh("release", "upload", RELEASE, pdf_path, "--clobber")
            log("  relizga yuklandi")

        cover_file = os.path.join(COVERS, bid + ".jpg")
        if prev.get("coverSrc") != cover_src or not os.path.exists(cover_file):
            try:
                if img:
                    ip = os.path.join(work, bid + ".img")
                    download(img["id"], ip)
                    make_cover(ip, cover_file, False)
                else:
                    if pdf_path is None:
                        pdf_path = os.path.join(work, bid + ".pdf")
                        download(fid, pdf_path)
                    make_cover(pdf_path, cover_file, True)
                log("  muqova tayyor")
            except Exception as e:  # muqovasiz ham ishlayveradi
                log("  muqova yasalmadi:", e)
                cover_src = None

        if pdf_path and os.path.exists(pdf_path):
            os.remove(pdf_path)

        books.append({
            "id": bid,
            "title": title,
            "author": author,
            "category": cat,
            "catOrder": cat_order.get(cat, 500),
            "url": ASSET_URL + bid + ".pdf",
            "cover": (RAW + "/covers/" + bid + ".jpg?v=" + (cover_src or "0")[-8:])
                     if os.path.exists(cover_file) else "",
            "size": int(f.get("size", 0) or 0),
            "added": f.get("createdTime", ""),
            "description": (f.get("description") or "").strip(),
            "lang": lang,
            "group": cat + "/" + group_key(title),
            "md5": pdf_md5,
            "pv": PROCESS_VERSION,
            "coverSrc": cover_src,
        })

    # To'g'ridan-to'g'ri yuborilgan kitoblar (qolda.py yozadi)
    qolda = os.path.join(ROOT, "qolda.json")
    if os.path.exists(qolda):
        for q in json.load(open(qolda, encoding="utf-8")).get("books", []):
            q = dict(q)
            if q["category"] in cat_order:
                q["catOrder"] = cat_order[q["category"]]
            books.append(q)

    # Drive'dan o'chirilgan kitoblarni olib tashlash
    current = {b["id"] for b in books}
    for fid in set(old) - current:
        log("O'chirildi:", old[fid].get("title"))
        gh("release", "delete-asset", RELEASE, fid + ".pdf", "-y", check=False)
        cf = os.path.join(COVERS, fid + ".jpg")
        if os.path.exists(cf):
            os.remove(cf)

    books.sort(key=lambda b: b["added"], reverse=True)
    if books != catalog.get("books"):
        catalog["books"] = books
        catalog["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        with open(CATALOG, "w", encoding="utf-8") as fh:
            json.dump(catalog, fh, ensure_ascii=False, indent=1)
        log(f"Katalog yangilandi: {len(books)} ta kitob")
    else:
        log(f"O'zgarish yo'q ({len(books)} ta kitob)")

    # Yangiliklar ("Yangiliklar" papkasidagi Google Doc'lar)
    try:
        build_news(root, list_folder, auth, RAW, ROOT, log, pub_id)
    except Exception as e:
        log("Yangiliklarda xato:", e)

    # GitHub 60 kun faoliyatsiz omborda jadvalni o'chirib qo'ymasligi uchun
    now = datetime.datetime.now(datetime.timezone.utc)
    if now.weekday() == 0 and now.hour == 0:
        os.makedirs(os.path.join(ROOT, ".github"), exist_ok=True)
        with open(os.path.join(ROOT, ".github", "keepalive.txt"), "w") as fh:
            fh.write(now.isoformat() + "\n")


if __name__ == "__main__":
    main()
