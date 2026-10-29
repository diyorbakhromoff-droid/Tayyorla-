"""Google Fonts shriftlarini static/fonts ga yuklab, mahalliy fonts.css yasaydi.

Video renderer internetsiz ishlashi va Mini App ko'rinishi videoga aynan mos kelishi uchun shriftlar repoda turadi.
Ishga tushirish: python -m scripts.fetch_fonts
"""

import hashlib
import re
import urllib.request

from app.config import ROOT

# Faqat kirill-ext (Ў Қ Ғ Ҳ, қозоқ va тожик harflari) va latin-ext (qoraqalpoq ǵ ń ı) ga ega shriftlar
FAMILIES = [
    "Onest:wght@400;500;600;700",
    "Alegreya:ital,wght@0,700;0,800;1,700",
    "Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,500;1,600",
    "Lora:ital,wght@0,500;0,600;0,700;1,500;1,600",
    "Yeseva+One",
    "Philosopher:ital,wght@0,400;0,700;1,400",
    "Comfortaa:wght@500;700",
    "Unbounded:wght@500;700;800",
    "Caveat:wght@500;700",
    "Rubik:wght@400;500;700",
]
SUBSETS = {"latin", "latin-ext", "cyrillic", "cyrillic-ext"}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
OUT = ROOT / "static" / "fonts"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    css_out = ["/* python -m scripts.fetch_fonts — Google Fonts (SIL Open Font License) */"]
    seen: dict[str, str] = {}
    for fam in FAMILIES:
        css = get(f"https://fonts.googleapis.com/css2?family={fam}&display=swap").decode()
        for subset, block in re.findall(r"/\* ([\w-]+) \*/\s*(@font-face \{.*?\})", css, re.S):
            if subset not in SUBSETS:
                continue
            m = re.search(r"url\((https://[^)]+\.woff2)\)", block)
            if not m:
                print("  woff2 topilmadi:", fam, subset)
                continue
            url = m.group(1)
            if url not in seen:
                family = re.search(r"font-family: '([^']+)'", block).group(1)
                name = f"{family.lower().replace(' ', '-')}-{hashlib.sha1(url.encode()).hexdigest()[:8]}.woff2"
                (OUT / name).write_bytes(get(url))
                seen[url] = name
            css_out.append(block.replace(url, seen[url]))
        print("ok", fam)
    (OUT / "fonts.css").write_text("\n".join(css_out) + "\n", encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT.glob("*.woff2"))
    print(f"{len(seen)} ta fayl, {total / 1024:.0f} KB")


if __name__ == "__main__":
    main()
