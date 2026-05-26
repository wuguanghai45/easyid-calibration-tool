"""Load Feishu integration settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FeishuSettings:
    """Static credentials and Bitable location (from env or .env file)."""

    app_id: str
    app_secret: str
    wiki_token: str
    table_id: str
    obj_type: str = "wiki"

    @classmethod
    def from_env(cls) -> FeishuSettings:
        app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        wiki_token = os.environ.get("FEISHU_WIKI_TOKEN", "").strip()
        table_id = os.environ.get("FEISHU_TABLE_ID", "").strip()
        obj_type = os.environ.get("FEISHU_OBJ_TYPE", "wiki").strip() or "wiki"

        missing = [
            name
            for name, value in (
                ("FEISHU_APP_ID", app_id),
                ("FEISHU_APP_SECRET", app_secret),
                ("FEISHU_WIKI_TOKEN", wiki_token),
                ("FEISHU_TABLE_ID", table_id),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "Missing required environment variables: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill in values."
            )

        return cls(
            app_id=app_id,
            app_secret=app_secret,
            wiki_token=wiki_token,
            table_id=table_id,
            obj_type=obj_type,
        )


def load_dotenv_if_present() -> None:
    """Load a .env file from the project root when python-dotenv is not required."""
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
