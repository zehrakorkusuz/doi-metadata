"""Configuration loaded from environment variables / .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OpenAIRE
    openaire_api_key: str = ""
    openaire_refresh_token: str = ""

    # OpenAlex
    openalex_email: str = ""
    openalex_api_key: str = ""

    # CrossRef
    crossref_email: str = ""

    # Unpaywall
    unpaywall_email: str = ""

    # Semantic Scholar
    semantic_scholar_api_key: str = ""

    # ORCID
    orcid_client_id: str = ""
    orcid_client_secret: str = ""

    # Entrez / PubMed
    entrez_email: str = ""
    entrez_api_key: str = ""  # 10 req/s with key, 3 req/s without

    # NIH Reporter
    nih_reporter_base_url: str = "https://api.reporter.nih.gov/v2"

    # Timeouts (seconds)
    http_timeout: float = 30.0
    http_max_retries: int = 3

    # User-Agent
    user_agent: str = "DOIphin/0.1 (https://github.com/Kaimen-Inc/doi-metadata)"

    model_config = {"env_file": str(Path.cwd() / ".env"), "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
