"""Settings and configuration management for Digestif."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base paths
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    DATA_DIR: Path = Path("data")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_USER_ID: int = 0

    @field_validator("TELEGRAM_ALLOWED_USER_ID", mode="before")
    @classmethod
    def _blank_user_id_to_zero(cls, v: Any) -> Any:
        # .env.example ships this key blank; an unset env var still overrides the int
        # default with "" once the key is present at all, which fails int parsing.
        if v == "":
            return 0
        return v

    # Gmail IMAP / SMTP
    DIGEST_GMAIL_ADDRESS: str = ""
    DIGEST_GMAIL_APP_PASSWORD: str = ""
    DELIVERY_EMAIL_TO: str = ""
    ALLOWED_FORWARDERS: str = ""

    # LLM keys
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_API_TOKEN: str = ""
    MISTRAL_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    EXA_API_KEY: str = ""
    APIFY_TOKEN: str = ""
    SEARXNG_URL: str = "http://searxng:8080"
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"

    # YAML configs cached
    _config_yaml: dict[str, Any] | None = None
    _providers_yaml: dict[str, Any] | None = None
    _profile_text: str | None = None

    @property
    def db_path(self) -> Path:
        return self.ensure_data_dir() / "digestif.db"

    @property
    def mail_dir(self) -> Path:
        p = self.ensure_data_dir() / "mail"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def media_dir(self) -> Path:
        p = self.ensure_data_dir() / "media"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def backups_dir(self) -> Path:
        p = self.ensure_data_dir() / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def digests_dir(self) -> Path:
        p = self.ensure_data_dir() / "digests"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_data_dir(self) -> Path:
        path = self.DATA_DIR
        if not path.is_absolute():
            path = self.BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def app_config(self) -> dict[str, Any]:
        if self._config_yaml is None:
            config_file = self.BASE_DIR / "config" / "config.yaml"
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    self._config_yaml = yaml.safe_load(f) or {}
            else:
                self._config_yaml = {}
        return self._config_yaml

    @property
    def providers_config(self) -> dict[str, Any]:
        if self._providers_yaml is None:
            providers_file = self.BASE_DIR / "config" / "providers.yaml"
            if providers_file.exists():
                with open(providers_file, "r", encoding="utf-8") as f:
                    self._providers_yaml = yaml.safe_load(f) or {}
            else:
                self._providers_yaml = {}
        return self._providers_yaml

    @property
    def user_profile(self) -> str:
        if self._profile_text is None:
            profile_file = self.BASE_DIR / "config" / "profile.md"
            if profile_file.exists():
                self._profile_text = profile_file.read_text(encoding="utf-8")
            else:
                self._profile_text = ""
        return self._profile_text

    @property
    def allowed_forwarder_emails(self) -> set[str]:
        if not self.ALLOWED_FORWARDERS:
            return set()
        return {addr.strip().lower() for addr in self.ALLOWED_FORWARDERS.split(",") if addr.strip()}


settings = Settings()
