"""The brand artwork for documents the server renders (receipts, the animal passport).

Embedded as data URIs so WeasyPrint never fetches a URL. The files in app/static/brand are
copies of the brand pack's, used exactly as supplied (BR-031).
"""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

_BRAND_DIR = Path(__file__).resolve().parent.parent / 'static' / 'brand'


@lru_cache(maxsize=4)
def logo_data_uri(name: str = 'logo-horizontal.svg') -> str | None:
    """A brand file as a data URI, or None when it is missing (the document renders without it)."""
    try:
        return 'data:image/svg+xml;base64,' + base64.b64encode((_BRAND_DIR / name).read_bytes()).decode('ascii')
    except OSError:
        return None
