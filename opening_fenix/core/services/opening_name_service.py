import os
import json
from typing import Optional, List, Dict
from opening_fenix.core.data_tools import get_base_path
from opening_fenix.core.logger import logger

_OPENINGS_CACHE: Optional[Dict[str, dict]] = None

def load_openings_database() -> Dict[str, dict]:
    """
    Loads and caches the chess openings database from assets/openings.json.
    Returns a dict mapping clean FEN (4 fields) to opening metadata.
    """
    global _OPENINGS_CACHE
    if _OPENINGS_CACHE is not None:
        return _OPENINGS_CACHE

    db_path = os.path.join(get_base_path(), "assets", "openings.json")
    if not os.path.exists(db_path):
        logger.warning(f"Openings database not found at {db_path}")
        _OPENINGS_CACHE = {}
        return _OPENINGS_CACHE

    try:
        with open(db_path, "r", encoding="utf-8") as f:
            _OPENINGS_CACHE = json.load(f)
            logger.info(f"Loaded {len(_OPENINGS_CACHE)} openings from {db_path}")
    except Exception as e:
        logger.error(f"Failed to load openings database: {e}")
        _OPENINGS_CACHE = {}

    return _OPENINGS_CACHE


def clean_fen(fen: str) -> str:
    """Normalizes a FEN to the first 4 fields: piece placement, active color, castling, en passant."""
    if not fen:
        return ""
    return " ".join(fen.strip().split(" ")[:4])


def lookup_fen(db: dict, fen: str) -> Optional[dict]:
    """Looks up a FEN in db, matching 4 fields or normalized en-passant '-'."""
    if not fen:
        return None
    parts = fen.strip().split()
    if len(parts) >= 4:
        c4 = " ".join(parts[:4])
        if c4 in db:
            return db[c4]
        c_no_ep = " ".join(parts[:3]) + " -"
        if c_no_ep in db:
            return db[c_no_ep]
    elif len(parts) >= 3:
        c_no_ep = " ".join(parts[:3]) + " -"
        if c_no_ep in db:
            return db[c_no_ep]
    return None


def get_suggested_variation_names(
    fen: str,
    lang: str = "de",
    ancestor_fens: Optional[List[str]] = None
) -> Optional[Dict[str, Optional[str]]]:
    """
    Returns suggested variation names for a position FEN only if this exact
    position starts a recognized opening/variation in the database.
    Does NOT fall back to ancestors so following moves in a line do not
    repeatedly suggest the same opening.
    """
    db = load_openings_database()
    if not db:
        return None

    target_lang = (lang or "de").lower()
    is_de = target_lang.startswith("de")

    # Only match if current position is an exact starting point in the database
    entry = lookup_fen(db, fen)
    if not entry:
        return None

    if is_de:
        v1 = entry.get("v1_de") or entry.get("v1_en")
        v2 = entry.get("v2_de") or entry.get("v2_en")
        v3 = entry.get("v3_de") or entry.get("v3_en")
        if v3 and v2 and v1:
            full_name_loc = f"{v1}: {v2}, {v3}"
        elif v2 and v1:
            full_name_loc = f"{v1}: {v2}"
        else:
            full_name_loc = v1 or entry.get("name", "")
    else:
        v1 = entry.get("v1_en")
        v2 = entry.get("v2_en")
        v3 = entry.get("v3_en")
        full_name_loc = entry.get("name", "")

    return {
        "eco": entry.get("eco", ""),
        "full_name": entry.get("name", ""),
        "full_name_localized": full_name_loc,
        "v1": v1 if v1 else None,
        "v2": v2 if v2 else None,
        "v3": v3 if v3 else None,
    }
