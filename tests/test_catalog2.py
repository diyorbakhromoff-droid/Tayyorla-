"""Tarifli (v2) shablonlar: python -m tests.test_catalog2"""

import json
import os

os.environ["BOT_TOKEN"] = "123456:TEST"

from fastapi import HTTPException  # noqa: E402

from app import catalog2  # noqa: E402
from app.catalog import TEMPLATES, catalog_meta, clean_order, render_catalog, tier_price  # noqa: E402


def rejects(fn) -> bool:
    try:
        fn()
    except HTTPException:
        return True
    return False


assert tier_price("standart") == 39000 and tier_price("premium") == 59000 and tier_price("vip") == 99000

v2 = [t for t in TEMPLATES.values() if t.get("v2")]
assert v2, "v2 shablonlar topilmadi"
meta = catalog_meta()
assert all(t.get("v2") for t in meta["templates"]), "katalogda faqat tarifli shablonlar ko'rinadi"
assert all(not TEMPLATES[x].get("legacy") for r in meta["relations"] for x in r["picks"])

for t in v2:
    sec = t["section"]
    assert t["tier"] in ("standart", "premium", "vip"), t["id"]
    assert set(t["blocks"]) <= {b.key for b in catalog2.BLOCKS2[sec]}, t["id"]
    assert all(f.key in {x.key for x in catalog2.FIELDS2[sec]} for f in catalog2.fields_for(t))
    demo = catalog2.DEMOS.get(sec)
    assert demo, f"{sec}/demo.json yo'q"
    # namuna sahifasi yig'iladi va mijoz ma'lumoti config ichida bo'ladi
    html = catalog2.render(t, catalog2.demo_config(t), "namuna", preview=False, demo=True)
    assert '<template id="dc-tpl">' in html and "DC.boot(Component)" in html, t["id"]
    assert "Siz ham shunday sayt yarating" not in html
    assert "/_blob/" not in html, f"{t['id']}: dizayndagi rasm havolasi qolib ketgan"

# tarif shablonga bog'langan: Standart narxida VIP shablon olinmaydi
vip = next(t for t in v2 if t["tier"] == "vip")
std = next((t for t in v2 if t["tier"] == "standart"), None)
assert rejects(lambda: clean_order({"template": vip["id"], "tarif": "standart", "data": {}}, strict=True))
cfg = clean_order({"template": vip["id"], "tarif": "standart", "data": {}}, strict=False)
assert cfg["tarif"] == "vip"

# olib tashlangan bloklar: faqat shablondagi bloklar saqlanadi, ko'rinishi hisoblanadi
t = std or vip
data = dict(catalog2.DEMOS[t["section"]])
body = {"template": t["id"], "tarif": t["tier"], "data": data, "hidden": [t["blocks"][0], "yoq-blok"]}
cfg = clean_order(body, strict=True)
assert cfg["hidden"] == [t["blocks"][0]]
b = catalog2.visible_blocks(t, cfg["data"], [], None, cfg["hidden"])
assert b[t["blocks"][0]] is False
if "galereya" in t["blocks"]:
    assert b["galereya"] is False  # suratsiz galereya ko'rinmaydi
html = render_catalog(cfg, "abc", preview=True)
conf = json.loads(html.split('<script id="site-config" type="application/json">')[1].split("</script>")[0])
assert conf["b"][t["blocks"][0]] is False and conf["urls"]["react"] == "/s/abc/react"
assert "NAMUNA" in html

# bloklar ro'yxati bo'sh ma'lumotda ham ishlaydi
cfg = clean_order({"template": t["id"], "tarif": t["tier"], "data": {}}, strict=False)
assert all(v is False or k in ("sham", "javob", "kun", "taymer", "rsvp", "sorov") for k, v in
           catalog2.visible_blocks(t, cfg["data"], [], None, []).items())

# rang palitralari: Standart 3, Premium 8, VIP 12; tarifdan ortig'i asl rangga qaytadi
prem = next(t for t in v2 if t["tier"] == "premium")
assert len(vip["colors"]) == 12 and len(prem["colors"]) == 8 and len(vip["swatch"]) == 12
assert catalog2.palette(prem, 9) == [0, 1.0, 1.0] and catalog2.palette(vip, 12) != [0, 1.0, 1.0]
assert clean_order({"template": prem["id"], "rang": 8, "data": {}}, strict=False)["rang"] == 8
assert clean_order({"template": prem["id"], "rang": 9, "data": {}}, strict=False)["rang"] == 1

print("catalog2: OK", len(v2), "ta shablon")
