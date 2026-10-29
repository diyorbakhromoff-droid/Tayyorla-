from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    bot_token: str = ""
    anthropic_api_key: str = ""
    base_url: str = "http://localhost:8000"
    admin_ids: str = ""
    rahmat_url: str = ""
    price: int = 25000  # eski (oddiy) shablonlar uchun
    price_standart: int = 25000
    price_premium: int = 49000
    price_vip: int = 79000
    max_edits: int = 10
    database_url: str = "sqlite+aiosqlite:///tayyorla.db"
    host: str = "0.0.0.0"
    port: int = 8000
    bot_username: str = "tayyorla_aibot"

    # Premium sifat uchun eng kuchli Opus modeli
    ai_model: str = "claude-opus-5-5"

    # ---- video taklifnoma
    # Bepul videoni olish uchun obuna bo'linadigan kanal (@username). Bo'sh bo'lsa obuna so'ralmaydi.
    channel_id: str = "@tayyorlaai"  # bepul videolar uchun obuna kanali (bot unda admin bo'lishi kerak)
    free_videos_per_day: int = 2
    video_price: int = 9900
    # Balansni to'ldirish summalari (so'm)
    topup_amounts: str = "9900,29700,49500,99000"
    # Har bir mehmonga shaxsiy video paketlari: «mehmonlar soni:narx»
    guest_packages: str = "15:39000,40:69000,100:119000,300:199000"
    video_fps: int = 30
    video_scale: int = 2  # 2 => 720x1280 (~40 s), 3 => 1080x1920 (~1 daqiqa, kuchliroq server kerak)
    video_seconds: int = 20
    video_max_per_hour: int = 10
    video_keep_days: int = 7

    @property
    def admins(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(" ", "").split(",") if x}

    @property
    def channel_username(self) -> str:
        c = self.channel_id.strip()
        for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
            if c.startswith(prefix):
                c = "@" + c[len(prefix):].strip("/")
        return c

    @property
    def channel_link(self) -> str:
        c = self.channel_username
        return f"https://t.me/{c.lstrip('@')}" if c.startswith("@") else ""

    @property
    def topups(self) -> list[int]:
        return [int(x) for x in self.topup_amounts.replace(" ", "").split(",") if x.isdigit()]

    @property
    def packages(self) -> list[tuple[int, int]]:
        out = []
        for part in self.guest_packages.replace(" ", "").split(","):
            if ":" in part:
                n, p = part.split(":", 1)
                if n.isdigit() and p.isdigit():
                    out.append((int(n), int(p)))
        return sorted(out)


settings = Settings()
MEDIA_DIR = ROOT / "media"
MEDIA_DIR.mkdir(exist_ok=True)
VIDEO_DIR = MEDIA_DIR / "video"
VIDEO_DIR.mkdir(exist_ok=True)
MUSIC_DIR = MEDIA_DIR / "music"
MUSIC_DIR.mkdir(exist_ok=True)
