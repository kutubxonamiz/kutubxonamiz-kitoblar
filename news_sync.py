"""Drive'dagi "Yangiliklar" papkasidagi Google Doc hujjatlarni ilova uchun
news.json ga aylantiradi.

Har bir hujjat = bitta yangilik:
- hujjat nomi = sarlavha
- ichidagi matn va rasmlar = maqola (rasmlar news/<id>/ papkasiga saqlanadi)
Hujjat o'chirilsa, yangilik ham ilovadan o'chadi.
"""
import io
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser

NEWS_FOLDER_NAMES = {"yangiliklar", "янгиликлар", "news"}
DOC_MIME = "application/vnd.google-apps.document"


def is_news_folder(name):
    return re.sub(r"^\s*\d+\s*[.)\-:]\s*", "", name).strip().lower() in NEWS_FOLDER_NAMES


class _DocParser(HTMLParser):
    """Google Docs HTML eksportini oddiy bloklarga ajratadi."""
    BLOCKS = {"p": "p", "h1": "h", "h2": "h", "h3": "h", "h4": "h", "li": "li", "title": None}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._kind = None
        self._buf = []
        self._skip = 0

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if self._kind and text:
            self.blocks.append({"type": self._kind, "text": text})
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self._skip += 1
        elif tag in self.BLOCKS:
            self._flush()
            self._kind = self.BLOCKS[tag]
        elif tag == "br":
            self._buf.append("\n")
        elif tag == "img":
            self._flush()
            src = dict(attrs).get("src", "")
            if src:
                self.blocks.append({"type": "img", "src": src})

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCKS:
            self._flush()
            self._kind = None

    def handle_data(self, data):
        if not self._skip and self._kind:
            self._buf.append(data)


def _export_zip(fid, auth):
    headers, extra = auth()
    url = (f"https://www.googleapis.com/drive/v3/files/{fid}/export?"
           + urllib.parse.urlencode(dict({"mimeType": "application/zip"}, **extra)))
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
        return zipfile.ZipFile(io.BytesIO(r.read()))


def _save_image(data, out_path):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((1200, 1600))
    im.save(out_path, "JPEG", quality=82, optimize=True, progressive=True)


def doc_to_blocks(fid, modified, auth, out_dir, url_prefix, log):
    """Google Doc -> [bloklar]; rasmlar out_dir ga saqlanadi."""
    z = _export_zip(fid, auth)
    html_name = next((n for n in z.namelist() if n.lower().endswith(".html")), None)
    if not html_name:
        return []
    parser = _DocParser()
    parser.feed(z.read(html_name).decode("utf-8", "replace"))
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    ver = re.sub(r"\D", "", modified)[-8:] or "0"
    blocks, n = [], 0
    for b in parser.blocks:
        if b["type"] != "img":
            blocks.append(b)
            continue
        src = urllib.parse.unquote(b["src"])
        member = next((m for m in z.namelist() if m.endswith(src) or src.endswith(m)), None)
        if not member:
            continue
        n += 1
        try:
            _save_image(z.read(member), os.path.join(out_dir, f"{n}.jpg"))
            blocks.append({"type": "img", "url": f"{url_prefix}/{n}.jpg?v={ver}"})
        except Exception as e:
            log("  rasm saqlanmadi:", e)
    if n == 0:
        shutil.rmtree(out_dir, ignore_errors=True)
    return blocks


ABOUT_NAMES = {"muallif haqida", "муаллиф ҳақида", "муаллиф хакида"}


def build_about(root_files, auth, raw_base, repo_root, log):
    """'Muallif haqida' hujjatidan about.json yasaydi (bo'sh bo'lsa — o'chiradi)."""
    path = os.path.join(repo_root, "about.json")
    out_dir = os.path.join(repo_root, "about")
    doc = next((f for f in root_files if f["mimeType"] == DOC_MIME
                and f["name"].strip().lower() in ABOUT_NAMES), None)
    old = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    if doc is None:
        if old is not None:
            os.remove(path)
            shutil.rmtree(out_dir, ignore_errors=True)
            log("Muallif haqida: hujjat yo'q, olib tashlandi")
        return
    modified = doc.get("modifiedTime", "")
    if old and old.get("modified") == modified:
        return
    blocks = doc_to_blocks(doc["id"], modified, auth, out_dir, f"{raw_base}/about", log)
    texts = [b for b in blocks if b["type"] != "img"]
    if not texts:
        if os.path.exists(path):
            os.remove(path)
        shutil.rmtree(out_dir, ignore_errors=True)
        log("Muallif haqida: hujjat bo'sh")
        return
    # Birinchi qisqa qator (sarlavha yoki oddiy) — muallif ismi
    name = ""
    for i, b in enumerate(blocks):
        if b["type"] == "img":
            continue
        if b["type"] in ("h", "p") and len(b["text"]) <= 60:
            name = b["text"]
            blocks = blocks[:i] + blocks[i + 1:]
        break
    photo = next((b["url"] for b in blocks if b["type"] == "img"), "")
    if photo:  # birinchi rasm — muallif surati, matn ichida takrorlanmaydi
        blocks = [b for b in blocks if not (b["type"] == "img" and b["url"] == photo)]
    data = {"modified": modified, "name": name, "photo": photo, "blocks": blocks}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    log("Muallif haqida: yangilandi")


def build_news(root_files, list_folder, auth, raw_base, repo_root, log, pub_id=lambda x: x):
    """news.json ni yangilaydi. True qaytaradi — agar o'zgarish bo'lsa."""
    news_path = os.path.join(repo_root, "news.json")
    news_dir = os.path.join(repo_root, "news")
    old = {}
    if os.path.exists(news_path):
        old = {n["id"]: n for n in json.load(open(news_path, encoding="utf-8")).get("items", [])}

    docs = []
    for folder in root_files:
        if folder["mimeType"] == "application/vnd.google-apps.folder" and is_news_folder(folder["name"]):
            docs += [f for f in list_folder(folder["id"]) if f["mimeType"] == DOC_MIME]

    items = []
    for d in docs:
        fid, modified = d["id"], d.get("modifiedTime", "")
        nid = pub_id(fid)
        prev = old.get(nid)
        if prev and prev.get("modified") == modified:
            items.append(prev)
            continue
        log("Yangilik:", d["name"])
        try:
            blocks = doc_to_blocks(fid, modified, auth, os.path.join(news_dir, nid),
                                   f"{raw_base}/news/{nid}", log)
        except Exception as e:
            log("  eksport qilinmadi:", e)
            if prev:
                items.append(prev)
            continue

        title = d["name"].strip()
        # Hujjat boshida sarlavha takrorlangan bo'lsa, olib tashlaymiz
        if blocks and blocks[0]["type"] in ("h", "p") and blocks[0]["text"].strip() == title:
            blocks = blocks[1:]
        text_blocks = [b["text"] for b in blocks if b["type"] in ("p", "li")]
        excerpt = " ".join(text_blocks)[:180]
        cover = next((b["url"] for b in blocks if b["type"] == "img"), "")
        items.append({
            "id": nid,
            "title": title,
            "date": d.get("createdTime", ""),
            "modified": modified,
            "cover": cover,
            "excerpt": excerpt,
            "blocks": blocks,
        })

    # O'chirilgan yangiliklarning rasmlarini tozalash
    current = {i["id"] for i in items}
    if os.path.isdir(news_dir):
        for name in os.listdir(news_dir):
            if name not in current:
                shutil.rmtree(os.path.join(news_dir, name), ignore_errors=True)

    items.sort(key=lambda i: i["date"], reverse=True)
    old_items = sorted(old.values(), key=lambda i: i["date"], reverse=True)
    if items == old_items and os.path.exists(news_path):
        log(f"Yangiliklar: o'zgarish yo'q ({len(items)} ta)")
        return False
    import datetime
    data = {
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "items": items,
    }
    with open(news_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    log(f"Yangiliklar yangilandi: {len(items)} ta")
    return True
