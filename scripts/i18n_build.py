"""Mini App va bot lug'atlarini yig'ish: python -m scripts.i18n_build

1. static/i18n/uz.json = bot.* kalitlari + scripts/i18n_app_uz.APP + katalog va video dizayn nomlari (tarjima uchun manba).
2. static/i18n/cy.json — o'zbekcha matndan qoidaga ko'ra kirillga o'giriladi ({...}, <teg>, havola va brendlar saqlanadi).
3. Qolgan tillar (ru, en, kaa, tg, kk) qo'lda tarjima qilinadi; skript ulardagi yetishmayotgan
   va ortiqcha kalitlarni, buzilgan {o'rinlar}ni ko'rsatadi (--check).
"""

import json
import re
import sys
from pathlib import Path

from app import i18n, video
from app.catalog import RELATIONS, catalog_meta
from scripts.i18n_app_uz import APP

DIR = Path(__file__).resolve().parent.parent / "static" / "i18n"
KEEP = re.compile(r"(\{[a-z_]+\}|<[^>]+>|https?://\S+|@\w+|\bTayyorla\b|\bTelegram\b|\bInstagram\b|\bYouTube\b|\bGoogle\b|\bYandex\b"
                  r"|\bClick\b|\bPayme\b|\bUzum\b|\bRahmat\b|\bVIP\b|\bPremium\b|\bStandart\b|\bMP3\b|\bM4A\b|\bOGG\b|\bWAV\b|\bMB\b|\bQR\b|\bmp3\b)")


def catalog_keys() -> dict:
    m = catalog_meta()
    out = {}
    for s in m["sections"]:
        out[f"csec.{s['key']}"] = s["title"]
    for t in m["tiers"]:
        out[f"tier.{t['key']}"] = t["title"]
        for i, f in enumerate(t["features"]):
            out[f"tierf.{t['key']}.{i}"] = f
    labels, hints = {}, {}
    for sec, fs in m["fields"].items():
        for f in fs:
            labels.setdefault(f["key"], {})[sec] = f["label"]
            if f.get("hint"):
                hints.setdefault(f["key"], {})[sec] = f["hint"]
    # bir xil nom — umumiy kalit, bo'limga qarab farq qilsa — har bo'lim uchun alohida (cf.toy.kimga)
    for prefix, table in (("cf", labels), ("cfh", hints)):
        for key, by_sec in table.items():
            if len(set(by_sec.values())) == 1:
                out[f"{prefix}.{key}"] = next(iter(by_sec.values()))
            else:
                out.update({f"{prefix}.{sec}.{key}": text for sec, text in by_sec.items()})
    for fs in m["fields"].values():
        for f in fs:
            for val, txt in (f.get("options") or {}).items():
                out.setdefault(f"cfo.{f['key']}.{val}", txt)
            for sk, sl, _ in f.get("sub") or []:
                out.setdefault(f"cfs.{f['key']}.{sk}", sl)
    for t in m["templates"]:
        out[f"tpld.{t['id']}"] = t["desc"]
    for k, r in RELATIONS.items():
        out[f"rel.{k}"] = r["title"]
        if r.get("why"):
            out[f"relw.{k}"] = r["why"]
    for d in video.DESIGNS.values():
        out[f"d.{d['id']}"] = d["name"]
        for p in d.get("palettes", []):
            out.setdefault(f"pal.{p['name']}", p["name"])
    return out


# qoidaga ko'ra o'girishdan keyin: ruscha o'zlashma so'zlar va oy nomlari kirill imlosida
CY_FIX = {"months": "январь,февраль,март,апрель,май,июнь,июль,август,сентябрь,октябрь,ноябрь,декабрь"}
CY_WORDS = [("аниматсия", "анимация"), ("Аниматсия", "Анимация"), ("ноябр»", "ноябрь»")]


def to_cy(text: str) -> str:
    parts = KEEP.split(text)
    out = "".join(p if i % 2 else i18n.to_cyrillic(p) for i, p in enumerate(parts))
    for a, b in CY_WORDS:
        out = out.replace(a, b)
    return out


def placeholders(s: str) -> set[str]:
    return set(re.findall(r"\{[a-z_]+\}", s))


def check(lang: str, src: dict) -> int:
    path = DIR / f"{lang}.json"
    if not path.exists():
        print(f"{lang}: fayl yo'q")
        return 1
    d = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in src if k not in d]
    extra = [k for k in d if k not in src]
    bad = [k for k in src if k in d and any(not placeholders(f) <= placeholders(src[k]) or not placeholders(f)
                                            for f in d[k].split("|")) and placeholders(src[k])]
    pipes = [k for k in d if "|" in d[k] and "{n}" not in src.get(k, "")]
    for name, keys in (("yetishmaydi", missing), ("ortiqcha", extra), ("o'rinlar buzilgan", bad), ("| ortiqcha", pipes)):
        if keys:
            print(f"{lang}: {name} ({len(keys)}): {', '.join(keys[:25])}")
    return len(missing) + len(bad) + len(pipes)


def merge_sections(src: dict) -> None:
    """Tarjima fayllariga bo'limga xos maydon nomlarini qo'shadi va manbada yo'q eski kalitlarni olib tashlaydi."""
    from scripts.i18n_sections import T as SECTION_TR
    for lang, extra in SECTION_TR.items():
        path = DIR / f"{lang}.json"
        if not path.exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        d.update({k: v for k, v in extra.items() if k in src})
        d = {k: d[k] for k in src if k in d}
        path.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{lang}: {len(d)} kalit")


def main() -> None:
    uz_path = DIR / "uz.json"
    if "--check-only" in sys.argv:  # hech narsa yozmaydi: python -m scripts.i18n_build --check-only ru
        src = json.loads(uz_path.read_text(encoding="utf-8"))
        langs = [a for a in sys.argv[1:] if not a.startswith("--")] or ["ru", "en", "kaa", "tg", "kk"]
        errors = sum(check(lang, src) for lang in langs)
        print("OK" if not errors else f"{errors} ta muammo")
        sys.exit(1 if errors else 0)
    current = json.loads(uz_path.read_text(encoding="utf-8"))
    bot = {k: v for k, v in current.items() if k.startswith("bot.")}
    uz = {**bot, **APP, **catalog_keys()}
    uz = dict(sorted(uz.items()))
    uz_path.write_text(json.dumps(uz, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cy = {k: CY_FIX.get(k) or to_cy(v) for k, v in uz.items()}
    (DIR / "cy.json").write_text(json.dumps(cy, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"uz: {len(uz)} kalit, cy yozildi")
    if "--merge" in sys.argv:
        merge_sections(uz)
    if "--check" in sys.argv:
        errors = sum(check(lang, uz) for lang in ("ru", "en", "kaa", "tg", "kk"))
        sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
