# Kutubxonamiz — kitoblar katalogi

**Kutubxonamiz** Android ilovasi kitoblarni shu ombordan oladi.

## Ilovani yuklab olish

https://github.com/kutubxonamiz/kutubxonamiz-kitoblar/releases/latest/download/Kutubxonamiz.apk

## Yangi kitob qo'shish

1. PDFni Google Drive'dagi **"Kutubxonamiz kitoblari"** papkasiga tashlang. Fayl nomi `Muallif - Kitob nomi.pdf` ko'rinishida bo'lsin.
2. Muqova qo'yish ixtiyoriy. PDF bilan bir xil nomli `.jpg` rasm qo'ysangiz, muqova shu rasmdan olinadi. Rasm bo'lmasa, PDFning birinchi beti muqova bo'ladi.
3. Bo'limga ajratmoqchi bo'lsangiz, papka ichida ichki papka oching, masalan "Aqida". Kitobni shu ichki papkaga tashlang.
4. Kitob 30 daqiqa ichida ilovada paydo bo'ladi.

Kitobni Drive'dan o'chirsangiz, u ilovadan ham o'chadi.

## Qanday ishlaydi

- `sync.py` har 30 daqiqada Drive papkasini tekshiradi.
- Yangi yoki o'zgargan PDFlarni **kitoblar** reliziga yuklaydi va `catalog.json` ni yangilaydi.
- `ilova-yuklash` shoxobchasiga yangi APK qo'yilsa, yangi versiya chiqariladi.
