"""PDF ichidagi hamma yashirin ma'lumotni tozalaydi (sahifalarga tegmaydi).

- Hujjat xususiyatlari: faqat sarlavha (va xohlansa muallif) qoladi
- XMP metama'lumot: hujjatdagi ham, har bir rasm/obyektdagi ham o'chiriladi
- Rasmlar ichidagi EXIF / XMP / Photoshop yozuvlari (kim yasagan, qaysi
  dastur, Canva hisob raqami) olib tashlanadi; rasmning o'zi o'zgarmaydi
"""
import pikepdf

DROP_KEYS = ("/Metadata", "/PieceInfo", "/LastModified")
KEEP_APP = {0xE0, 0xE2, 0xEE}  # JFIF, ICC rang profili, Adobe (ranglar to'g'ri chiqishi uchun)


def strip_jpeg(data: bytes) -> bytes:
    if data[:2] != b"\xff\xd8":
        return data
    out, i, n = bytearray(b"\xff\xd8"), 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return data  # kutilmagan tuzilma — tegmaymiz
        m = data[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m == 0xDA:  # rasm ma'lumoti boshlandi — qolgani o'zgarmaydi
            out += data[i:]
            return bytes(out)
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        seg = data[i:i + 2 + seg_len]
        if (0xE0 <= m <= 0xEF and m not in KEEP_APP) or m == 0xFE:
            pass  # EXIF, XMP, Photoshop, izohlar — tashlanadi
        else:
            out += seg
        i += 2 + seg_len
    return data


def is_dct(obj):
    f = obj.get("/Filter")
    if f is None:
        return False
    if isinstance(f, pikepdf.Array):
        return len(f) == 1 and f[0] == "/DCTDecode"
    return f == "/DCTDecode"


def tozala(src, dst, title, author=""):
    with pikepdf.open(src, allow_overwriting_input=True) as pdf:
        for k in list(pdf.docinfo.keys()):
            del pdf.docinfo[k]
        if title:
            pdf.docinfo["/Title"] = title
        if author:
            pdf.docinfo["/Author"] = author
        for k in DROP_KEYS + ("/SpiderInfo",):
            if k in pdf.Root:
                del pdf.Root[k]
        if "/Names" in pdf.Root and "/EmbeddedFiles" in pdf.Root.Names:
            del pdf.Root.Names["/EmbeddedFiles"]
        for obj in pdf.objects:
            if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
                for k in DROP_KEYS:
                    if k in obj:
                        del obj[k]
            if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == "/Image" and is_dct(obj):
                raw = obj.read_raw_bytes()
                new = strip_jpeg(raw)
                if new != raw:
                    obj.write(new, filter=pikepdf.Name("/DCTDecode"),
                              decode_parms=obj.get("/DecodeParms"))
        pdf.save(dst)
