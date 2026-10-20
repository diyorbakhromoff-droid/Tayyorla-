from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..catalog import site_price
from ..config import settings
from ..surprise import locked_until, owner_url
from ..sites import CATEGORIES, PALETTES


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so'm"


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.base_url.startswith("https://"):
        kb.button(text="✨ Sayt yaratish — 25 ta dizayn", web_app=WebAppInfo(url=f"{settings.base_url}/app"))
        kb.button(text="📅 Yaqinlarim — sanalarni eslatib turaman", callback_data="people")
        kb.button(text="📂 Mening saytlarim", callback_data="my")
        kb.button(text="⌨️ Oddiy shablonlar (tugmalar orqali)", callback_data="legacy")
    else:
        return legacy_menu()
    kb.adjust(1)
    return kb.as_markup()


def legacy_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in CATEGORIES.values():
        kb.button(text=c.title, callback_data=f"cat:{c.key}")
    kb.button(text="📅 Yaqinlarim", callback_data="people")
    kb.button(text="📂 Mening saytlarim", callback_data="my")
    kb.adjust(1)
    return kb.as_markup()


def skip() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⏭ O'tkazib yuborish", callback_data="skip")
    return kb.as_markup()


def message_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ AI chiroyli yozib bersin", callback_data="msg:ai")
    kb.button(text="✍️ O'zim yozaman", callback_data="msg:own")
    kb.adjust(1)
    return kb.as_markup()


def ai_review() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ma'qul", callback_data="ai:ok")
    kb.button(text="🔄 Boshqa variant", callback_data="ai:again")
    kb.button(text="✍️ O'zim yozaman", callback_data="msg:own")
    kb.adjust(2, 1)
    return kb.as_markup()


def done(text: str = "✅ Tayyor", optional: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=text, callback_data="done")
    if optional:
        kb.button(text="⏭ O'tkazib yuborish", callback_data="skip")
    kb.adjust(1)
    return kb.as_markup()


def choice(options: dict[str, str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, title in options.items():
        kb.button(text=title, callback_data=f"choice:{value}")
    kb.adjust(2)
    return kb.as_markup()


def palettes() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for k, p in PALETTES.items():
        kb.button(text=p["title"], callback_data=f"pal:{k}")
    kb.adjust(2)
    return kb.as_markup()


def features(category: str, enabled: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for k, title in CATEGORIES[category].features.items():
        kb.button(text=("✅ " if k in enabled else "▫️ ") + title, callback_data=f"feat:{k}")
    kb.button(text="🚀 Saytni yaratish", callback_data="done")
    kb.adjust(1)
    return kb.as_markup()


def site_actions(site) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👀 Saytni ochish", url=owner_url(site))
    kb.button(text="✏️ Tahrirlash", callback_data=f"edit:{site.id}")
    kb.button(text="⏰ Syurpriz: yoqilgan ✅" if locked_until(site.config) else "⏰ Syurpriz ochilish (00:00 da)", callback_data=f"surprise:{site.id}")
    if site.status == "draft":
        kb.button(text=f"💳 Linkni olish — {money(site_price(site.config))}", callback_data=f"buy:{site.id}")
    has_rsvp = site.config.get("features", {}).get("rsvp") or site.config.get("template") == "toy-maktub"
    if has_rsvp and site.paid:
        kb.button(text="📋 Mehmonlar ro'yxati", callback_data=f"guests:{site.id}")
    kb.button(text="🏠 Bosh menyu", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


def edit_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tahrirni tugatish", callback_data="edit_done")
    return kb.as_markup()


def pay(site) -> InlineKeyboardMarkup:
    site_id = site.id
    kb = InlineKeyboardBuilder()
    if settings.rahmat_url:
        kb.button(text=f"💳 To'lash — {money(site_price(site.config))}", url=settings.rahmat_url)
    kb.button(text="✅ To'ladim", callback_data=f"paid:{site_id}")
    kb.button(text="⬅️ Orqaga", callback_data=f"site:{site_id}")
    kb.adjust(1)
    return kb.as_markup()


def admin_review(site_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"approve:{site_id}")
    kb.button(text="❌ Rad etish", callback_data=f"reject:{site_id}")
    kb.adjust(2)
    return kb.as_markup()
