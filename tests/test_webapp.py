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
print("✅ Mini App tekshiruvlari o'tdi")
