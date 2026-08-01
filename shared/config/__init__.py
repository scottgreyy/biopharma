"""Config package. Import `get_settings` from here."""
from shared.config.settings import Settings, get_settings, ROOT_DIR, DATA_DIR

__all__ = ["Settings", "get_settings", "ROOT_DIR", "DATA_DIR"]
