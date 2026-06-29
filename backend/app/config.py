from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_pdf_font_path() -> Path:
    docker_font = Path("/app/fonts/NotoSansCJKjp-Regular.ttf")
    if docker_font.exists():
        return docker_font
    return Path(__file__).resolve().parents[2] / "fonts" / "NotoSansCJKjp-Regular.ttf"


class Settings(BaseSettings):
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    default_model: str = "gpt-4.1-mini"
    default_target_language: str = "ja"
    pdf_font_path: Path = _default_pdf_font_path()
    strict_mode: bool = True
    storage_dir: Path = Path("storage")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
