"""All tunable thresholds live here. Values can be overridden by CHECKER_* env vars
or by data/settings.json (written by the settings page)."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Bump when extraction/fingerprint/matching logic changes; `rescan` recomputes stale rows.
PIPELINE_VERSION = 2


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHECKER_")

    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 2

    # identity
    filename_regex: str = r"^(?P<student_id>[A-Za-z0-9]+)_.*\.pdf$"
    student_id_regex: str = r"\b(?:PES\d[A-Za-z0-9]{8,12}|[A-Za-z]{0,2}\d{6,10})\b"
    # SRN pattern used to name students from the filename or cover page (PES1UG25CS138, PES1202604133)
    srn_regex: str = r"PES\d[A-Z0-9]{8,12}"

    # extraction
    render_dpi: int = 150
    min_image_px: int = 80
    uniform_std: float = 3.0
    embedded_coverage_min: float = 0.6
    max_stored_side: int = 2000

    # OCR: auto | rapidocr | tesseract
    ocr_engine: str = "auto"
    ocr_upscale_below: int = 1000
    ocr_dark_mean: int = 110

    # hashing / matching
    phash_size: int = 12
    phash_near: int = 10
    phash_exact: int = 2
    shingle_k: int = 5
    min_line_chars: int = 12
    min_text_tokens: int = 8  # an image with at least this many OCR words counts as text-rich
    top_n: int = 25
    min_shared_shingles: int = 3
    text_containment_min: float = 0.3
    orb_min_inliers: int = 25
    code_k: int = 10
    code_w: int = 4
    code_containment_min: float = 0.5  # code structure is generic; demand more overlap than for text

    # scoring
    common_fraction: float = 0.25
    single_source_high: float = 0.5
    collage_high: float = 0.6
    collage_min_sources: int = 3
    rare_max_submissions: int = 3
    min_idf_population: int = 20  # early on N is tiny; treat it as at least this for rarity weights
    min_source_share: float = 0.05  # a source counts toward num_sources above this share
    tier_medium_coverage: float = 0.3
    metadata_close_seconds: int = 120
    common_producers: list[str] = ["print to pdf", "microsoft", "skia", "quartz", "libreoffice", "chrome",
                                   "google docs", "pdfium", "ghostscript", "macos", "ios", "wkhtmltopdf"]
    cluster_min_edge: float = 1.0  # summed rarity weight of shared items for a cluster edge

    # feature flags
    enable_sscd: bool = False
    enable_tamper: bool = False

    @property
    def inbox(self) -> Path:
        """Watched folder: drop PDFs into inbox/<assignment name>/."""
        return self.data_dir / "inbox"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'checker.db'}"


def settings_file(data_dir: Path = Path("data")) -> Path:
    return data_dir / "settings.json"


@lru_cache
def get_settings() -> Settings:
    base = Settings()
    f = settings_file(base.data_dir)
    if f.exists():
        return Settings(**{**base.model_dump(), **json.loads(f.read_text())})
    return base


def save_overrides(values: dict) -> Settings:
    s = get_settings()
    f = settings_file(s.data_dir)
    current = json.loads(f.read_text()) if f.exists() else {}
    current.update(values)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(current, indent=2, default=str))
    get_settings.cache_clear()
    return get_settings()
