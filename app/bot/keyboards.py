from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import settings
from ..sites import CATEGORIES, PALETTES


def money(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " so'm"


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in CATEGORIES.values():
        kb.button(text=c.title, callback_data=f"cat:{c.key}")
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
    kb.button(text="👀 Saytni ochish", url=site.url + ("?owner=1" if site.paid else ""))
    kb.button(text="✏️ Tahrirlash", callback_data=f"edit:{site.id}")
    if site.status == "draft":
        kb.button(text=f"💳 Linkni olish — {money(settings.price)}", callback_data=f"buy:{site.id}")
    if site.config.get("features", {}).get("rsvp") and site.paid:
        kb.button(text="📋 Mehmonlar ro'yxati", callback_data=f"guests:{site.id}")
    kb.button(text="🏠 Bosh menyu", callback_data="home")
    kb.adjust(1)
    return kb.as_markup()


def edit_mode() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tahrirni tugatish", callback_data="edit_done")
    return kb.as_markup()


def pay(site_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if settings.rahmat_url:
        kb.button(text=f"💳 To'lash — {money(settings.price)}", url=settings.rahmat_url)
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
