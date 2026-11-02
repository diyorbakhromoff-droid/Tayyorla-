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

# kiyinish uslubi ixtiyoriy: yangi buyurtmada va namunada o'chiq, mijoz qo'shsa ko'rinadi
dress_t = next(t for t in v2 if "dress" in t["blocks"])
assert clean_order({"template": dress_t["id"], "data": {}}, strict=False)["hidden"] == ["dress"]
assert clean_order({"template": dress_t["id"], "data": {}, "hidden": []}, strict=False)["hidden"] == []
assert catalog2.demo_config(dress_t)["hidden"] == ["dress"] and "dress_kod" not in catalog2.demo_config(dress_t)["data"]
assert next(b for b in catalog2.block_meta(dress_t) if b["key"] == "dress")["optional"] is True
assert next(f for f in meta["fields2"]["toy"] if f["key"] == "dress_kod")["optional"] is True
assert "Kechki uslub" not in catalog2.render(dress_t, catalog2.demo_config(dress_t), "namuna", preview=False, demo=True)

# olib tashlangan bloklar: «muhim savol» (sevgi) va «bazmga taklif» (tug'ilgan kun) yangi buyurtmada va namunada yo'q
for t in v2:
    assert not set(t["blocks"]) & catalog2.RETIRED_BLOCKS.get(t["section"], set()), t["id"]
# «savol»li 7 ta VIP shablon «javob»ga o'tkazildi; mexanizmni eski manifest kabi sintetik nusxada tekshiramiz
sv = next((t for t in v2 if "savol" in t["retired"]), None) or dict(next(t for t in v2 if t["section"] == "sevgi"), retired=["savol"])
assert "savol" not in {f.key for f in catalog2.fields_for(sv)} and "savol" not in catalog2.demo_config(sv)["data"]
assert "savol" not in clean_order({"template": sv["id"], "data": {"kimga": "A", "savol": "Turmushga chiqasanmi?"}}, strict=False)["data"]
assert catalog2.visible_blocks(sv, {"savol": "Eski savol"}, [], None, [])["savol"] is True  # eski sotilgan sayt o'zgarmaydi
assert catalog2.visible_blocks(sv, {}, [], None, [])["savol"] is False
tk = next(t for t in v2 if "bazm" in t["retired"])
assert "bazm_sana" not in catalog2.demo_config(tk)["data"] and "Bahor" not in catalog2.render(tk, catalog2.demo_config(tk), "namuna", preview=False, demo=True)

# marosim turlari: to'y shablonlari fotiha / qizlar bazmi / kelin salomga moslashadi
assert catalog2.marosim_text("NIKOH TO’YIGA TAKLIFNOMA, nikoh to’yimizga", "fotiha") == "FOTIHA TO’YIGA TAKLIFNOMA, fotiha to’yimizga"
assert catalog2.marosim_text("Nikoh to’yi sharafiga", "qizlar") == "Qizlar bazmi sharafiga"
assert catalog2.marosim_text("NIKOH TO’YIGA, nikoh to’yi", "kelin") == "KELIN SALOMGA, kelin salom"
assert catalog2.marosim_text("nikoh to’yi", "nikoh") == "nikoh to’yi"
toy_t = next(t for t in v2 if t["section"] == "toy")
cfg = catalog2.demo_config(toy_t)
cfg["data"]["marosim"] = "fotiha"
page = catalog2.render(toy_t, cfg, "namuna", preview=False, demo=True)
assert "Fotiha to\'yiga taklifnoma" in page or "fotiha to\'yiga taklifnoma" in page or "fotiha to'yiga taklifnoma" in page.lower()
assert clean_order({"template": toy_t["id"], "data": {"marosim": "qizlar"}}, strict=False)["data"]["marosim"] == "qizlar"
assert "marosim" not in clean_order({"template": toy_t["id"], "data": {"marosim": "yoq"}}, strict=False)["data"]
assert catalog2.page_title("osh", {"marosim": "sunnat", "mezbon": "Karimovlar oilasi"}) == "Karimovlar oilasi — sunnat to'yiga taklifnoma"
assert [f.key for f in catalog2.FIELDS2["osh"]][:1] == ["marosim"] and "osh" in catalog2.DEMOS

# rang palitralari: Standart 3, Premium 8, VIP 12; tarifdan ortig'i asl rangga qaytadi
prem = next(t for t in v2 if t["tier"] == "premium")
assert len(vip["colors"]) == 12 and len(prem["colors"]) == 8 and len(vip["swatch"]) == 12
assert catalog2.palette(prem, 9) == [0, 1.0, 1.0] and catalog2.palette(vip, 12) != [0, 1.0, 1.0]
assert clean_order({"template": prem["id"], "rang": 8, "data": {}}, strict=False)["rang"] == 8
assert clean_order({"template": prem["id"], "rang": 9, "data": {}}, strict=False)["rang"] == 1

print("catalog2: OK", len(v2), "ta shablon")
