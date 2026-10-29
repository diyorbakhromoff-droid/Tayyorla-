"""Mini App API tekshiruvlari: python -m tests.test_webapp"""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

os.environ["BOT_TOKEN"] = "123456:TEST"

from fastapi import HTTPException  # noqa: E402

from app.webapp import check_init_data, clean_answers  # noqa: E402


def sign(user: dict, token="123456:TEST", age=0) -> str:
    pairs = {"auth_date": str(int(time.time()) - age), "user": json.dumps(user)}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def rejects(fn) -> bool:
    try:
        fn()
    except HTTPException:
        return True
    return False


assert check_init_data(sign({"id": 7}))["id"] == 7
assert rejects(lambda: check_init_data(sign({"id": 7}, token="999:OTHER")))  # boshqa bot imzosi
assert rejects(lambda: check_init_data(sign({"id": 7}, age=3 * 86400)))  # eskirgan
assert rejects(lambda: check_init_data(sign({"id": 7}).replace("7", "8", 1)))  # o'zgartirilgan
assert rejects(lambda: check_init_data(""))

a = clean_answers("birthday", {
    "name": " Madina ", "date": "24.10.2026", "sender": "Oila", "message": "Salom",
    "photos": ["/media/../../etc/passwd", "https://evil/x.jpg"], "palette": "nope",
    "features": ["confetti", "hack"], "evil": "x",
}, strict=True)
assert a["name"] == "Madina" and a["photos"] == [] and a["palette"] == "atirgul"
assert a["features"] == ["confetti"] and "evil" not in a
assert rejects(lambda: clean_answers("birthday", {"name": "A"}, strict=True))  # majburiy maydonlar yo'q
assert rejects(lambda: clean_answers("birthday", {"date": "32.13.2026"}, strict=False))
assert rejects(lambda: clean_answers("nope", {}, strict=False))
assert clean_answers("baby", {"gender": "alien"}, strict=False)["gender"] is None
# Mini App sahifasi: skriptlar versiya bilan (Telegram keshi yangilanishi uchun), barcha bo'limlar ulanadi
import asyncio as _asyncio  # noqa: E402
import re as _re0  # noqa: E402
from app.webapp import app_page  # noqa: E402

_html = _asyncio.run(app_page()).body.decode()
assert "__V__" not in _html and _re0.search(r"core\.js\?v=\d+", _html)
for _m in ("core", "home", "videos", "sites", "events", "profile"):
    assert f"/static/app/{_m}.js?v=" in _html, _m

print("✅ Mini App tekshiruvlari o'tdi")

# ---------------------------------------------------------------- katalog shablonlari
import json as _json  # noqa: E402
import re as _re  # noqa: E402

from app.catalog import clean_order, render_catalog  # noqa: E402

base = {"template": "tk-tort", "data": {"kimga": "Madina", "kimdan": "Ali", "sana": "2026-10-24", "matn": "Salom",
        "savollar": [{"savol": "S?", "javoblar": ["a", "b"], "togri": 5}], "sirli_xabar": "sir"}}

std = clean_order({**base, "tarif": "standart", "rang": 9}, strict=True)
assert std["rang"] == 1, "standartda 9-rang bo'lmaydi"
assert "savollar" not in std["data"] and "sirli_xabar" not in std["data"], "premium maydonlar standartda yo'q"
prem = clean_order({**base, "tarif": "premium", "rang": 9}, strict=True)
assert prem["rang"] == 9 and prem["data"]["savollar"][0]["togri"] == 1 and prem["data"]["sirli_xabar"] == "sir"
assert rejects(lambda: clean_order({**base, "template": "tk-maktub", "tarif": "premium"}, strict=False))  # VIP shablon
assert clean_order({**base, "template": "tk-maktub", "tarif": "vip"}, strict=False)["tarif"] == "vip"
assert rejects(lambda: clean_order({**base, "data": {"kimga": "A"}, "tarif": "vip"}, strict=True))  # majburiy maydonlar
assert rejects(lambda: clean_order({**base, "template": "../../etc"}, strict=False))
assert rejects(lambda: clean_order({**base, "data": {"sana": "24.10"}}, strict=False))
assert clean_order({**base, "data": {"video": "javascript:alert(1)"}}, strict=False)["data"].get("video") is None
assert clean_order({**base, "photos": ["/media/../x", "https://evil/x.jpg"]}, strict=False)["photos"] == []

# sahifa: ma'lumot joyiga tushadi, skriptdan chiqib ketolmaydi, tarifni havola orqali o'zgartirib bo'lmaydi
evil = clean_order({**base, "tarif": "standart", "data": {**base["data"], "matn": "</script><script>alert(1)</script>"}}, strict=False)
page = render_catalog(evil, "abc", preview=False)
cfg_json = _re.search(r'<script id="site-config" type="application/json">(.*?)</script>', page, _re.S).group(1)
cfg = _json.loads(cfg_json)
assert cfg["kimga"] == "Madina" and cfg["tarif"] == "standart" and cfg["demo"] is False
assert "</script><script>alert" not in page
assert "new URLSearchParams(CFG.demo ? location.search : '')" in page and "NAMUNA" not in page
assert "t.me/tayyorla_aibot" in page
assert "NAMUNA • TAYYORLA" in render_catalog(evil, "abc", preview=True)
vip_toy = clean_order({"template": "toy-maktub", "tarif": "vip", "data": {}}, strict=False)
assert "/s/xyz/anketa" in render_catalog(vip_toy, "xyz", preview=False)
print("✅ Katalog tekshiruvlari o'tdi")

# yangi Premium dizaynlar: standart tarifda tanlanmaydi, dvigatelga to'g'ri ulangan
from app.catalog import TEMPLATES, catalog_meta  # noqa: E402
from app.config import ROOT as ROOT_DIR  # noqa: E402

NEW = ["tk-salyut", "toy-parda", "sv-yurak", "fz-quti", "uz-muz"]
assert len(TEMPLATES) == 30 and all(TEMPLATES[t].get("premium") for t in NEW)
meta_ids = {t["id"]: t for t in catalog_meta()["templates"]}
assert all(meta_ids[t]["premium"] and meta_ids[t]["new"] for t in NEW)
for tid in NEW:
    sec = TEMPLATES[tid]["section"]
    data = {"kimga": "Madina", "kimdan": "Ali", "sana": "2026-10-24", "matn": "Salom", "kuyov": "Jasur", "kelin": "Malika",
            "vaqt": "18:00", "manzil_nomi": "Navro'z", "manzil": "Toshkent", "jins": "qiz"}
    assert rejects(lambda: clean_order({"template": tid, "tarif": "standart", "data": data}, strict=False)), tid
    order = clean_order({"template": tid, "tarif": "premium", "rang": 15, "data": data}, strict=True)
    assert order["rang"] == 1, "premiumda 15-rang bo'lmaydi"
    page = render_catalog(order, "abc", preview=False)
    cfg = _json.loads(_re.search(r'<script id="site-config" type="application/json">(.*?)</script>', page, _re.S).group(1))
    assert cfg["demo"] is False and cfg["tarif"] == "premium" and cfg["kimdan"] == "Ali", tid
    assert "META.minSel && SEL < META.minSel" in page and f"skin-{tid}" in page and page.count('data-block="hero"') == 1
    assert (ROOT_DIR / "catalog" / "thumb" / f"{tid}.jpg").is_file()
print("✅ Yangi Premium dizaynlar tekshiruvi o'tdi")
