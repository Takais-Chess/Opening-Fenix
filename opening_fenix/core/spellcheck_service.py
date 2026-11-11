"""
Spellcheck Service for Opening Fenix.
Provides lightweight, offline spell-checking using pyspellchecker,
enhanced with chess terminology, SAN algebraic notation recognition,
and a persistent user dictionary.
"""

import os
import re
import json
import logging
from typing import Optional, List, Set, Dict, Tuple

logger = logging.getLogger(__name__)

# Try importing pyspellchecker gracefully
try:
    from spellchecker import SpellChecker
    SPELLCHECKER_AVAILABLE = True
except ImportError:
    SpellChecker = None
    SPELLCHECKER_AVAILABLE = False

# Regex for Standard Algebraic Chess Notation (German & English) and annotations
# Examples: e4, exd5, Nf3, Sf3, Lxf7+, Qh5#, O-O, 0-0, 0-0-0, 1., 1..., e8=Q
_SAN_PATTERN = re.compile(
    r'^(?:'
    r'[1-9]\d*\.{1,3}|'  # Move numbers: 1. or 1...
    r'(?:[KQRBNKDTSLBkqrbnkdtslb]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QQRBNKDTSLBqqrbnkdtslb])?)|' # SAN moves
    r'(?:O-O(?:-O)?|0-0(?:-0)?)' # Castling
    r')[+#=!?~]*$',
    re.IGNORECASE
)

# Common chess terms, openings, and player names across German and English
CHESS_VOCABULARY = {
    # Pieces & Board
    "fianchetto", "fianchettieren", "fianchettiert", "zugzwang", "zwischenzug", "en-passant",
    "gambit", "blunder", "repertoire", "repertoires", "engine", "stockfish", "lichess", "chess.com",
    "elo", "fide", "eval", "centipawn", "centipawns", "tempo", "tempi", "abtausch", "abtauschen",
    "schachmatt", "patt", "gabel", "fesselung", "spieß", "grundreihe", "grundreihenmatt",
    "doppelbauer", "doppelbauern", "freibauer", "freibauern", "isolani", "hängefiguren",
    "rochade", "kurze", "lange", "damenflügel", "königsflügel", "flügelseite",
    "turmendspiel", "turmendspiele", "bauernendspiel", "bauernendspiele",
    "läuferendspiel", "springerendspiel", "damenendspiel", "leichtfigurenendspiel",
    "eröffnung", "eröffnungen", "mittelspiel", "endspiel", "mattnetz", "eröffnungsfalle",
    "remis", "dauerschach", "dreifache", "zugwiederholung", "voreinstellung",
    # Openings
    "sizilianisch", "sizilianische", "sizilianischen", "sicilian",
    "französisch", "französische", "french",
    "caro-kann", "skandinavisch", "skandinavische", "scandinavian",
    "königsindisch", "königsindische", "kings-indian", "king's-indian",
    "damenindisch", "damenindische", "queens-indian", "queen's-indian",
    "grünfeld", "gruenfeld", "grünfeld-indisch",
    "nimzowitsch", "nimzowitsch-indisch", "nimzo-indian",
    "réti", "reti", "katalanisch", "katalanische", "catalan",
    "najdorf", "scheveningen", "sveshnikov", "kalashnikov", "taimanov", "kan",
    "paulsen", "rauzer", "sozin", "richter-rauzer", "boleslavsky", "chigorin",
    "breyer", "zaitsev", "archangelsk", "ruy", "lopez", "spanisch", "spanische",
    "italienisch", "italienische", "italian", "giuoco", "piano", "evans",
    "scotch", "schottisch", "schottische", "vienna", "wiener",
    "petrov", "petroff", "philidor", "benoni", "benko", "volga", "budapest",
    "albin", "slawisch", "slawische", "slav", "semi-slav", "meran", "chebanenko",
    "stonewall", "dutch", "holländisch", "holländische", "leningrad",
    "colle", "london", "london-system", "trompowsky", "torre", "jobava",
    "modern", "pirc", "alekhine", "center-game", "blackmar-diemer",
    # Players
    "morphy", "steinitz", "lasker", "capablanca", "euwe", "botvinnik", "smyslov",
    "tal", "petrosian", "spassky", "fischer", "karpov", "kasparov", "kramnik",
    "anand", "carlsen", "ding", "liren", "gukesh", "caruana", "nakamura",
    "nepomniachtchi", "firouzja", "praggnanandhaa", "vidit", "keymer"
}

# Supported ISO languages in pyspellchecker
SUPPORTED_LANGUAGES = {"de", "en", "es", "fr", "pt", "ru", "it", "nl"}


class SpellCheckService:
    """Central service managing spellcheckers, vocabulary, and user dictionaries."""
    
    _instance: Optional['SpellCheckService'] = None

    @classmethod
    def get_instance(cls) -> 'SpellCheckService':
        if cls._instance is None:
            cls._instance = SpellCheckService()
        return cls._instance

    def __init__(self):
        self._checkers: Dict[str, Optional[SpellChecker]] = {}
        self._user_dictionary: Set[str] = set()
        self._ignored_words: Set[str] = set()
        self._listeners: Set = set()
        self._enabled: bool = True
        self._user_dict_path: Optional[str] = None
        self._initialized: bool = False
        self._init_service()

    def _init_service(self):
        if self._initialized:
            return
        self._load_user_dictionary()
        self._load_config_state()
        self._initialized = True

    def _get_user_dict_path(self) -> str:
        if not self._user_dict_path:
            try:
                from opening_fenix.core.utils import get_user_dir
                user_dir = get_user_dir()
            except Exception:
                user_dir = os.path.expanduser("~")
            self._user_dict_path = os.path.join(user_dir, "user_dictionary.txt")
        return self._user_dict_path

    def _load_user_dictionary(self):
        dict_path = self._get_user_dict_path()
        if os.path.exists(dict_path):
            try:
                with open(dict_path, "r", encoding="utf-8") as f:
                    for line in f:
                        w = line.strip().lower()
                        if w and not w.startswith("#"):
                            self._user_dictionary.add(w)
            except Exception as e:
                logger.warning(f"Error loading user dictionary from {dict_path}: {e}")

    def _save_user_dictionary(self):
        dict_path = self._get_user_dict_path()
        try:
            os.makedirs(os.path.dirname(dict_path), exist_ok=True)
            with open(dict_path, "w", encoding="utf-8") as f:
                f.write("# Opening Fenix User Dictionary\n")
                for w in sorted(self._user_dictionary):
                    f.write(f"{w}\n")
        except Exception as e:
            logger.warning(f"Error saving user dictionary to {dict_path}: {e}")

    def _load_config_state(self):
        try:
            from opening_fenix.core.utils import get_user_dir
            cfg_path = os.path.join(get_user_dir(), "config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self._enabled = bool(cfg.get("spellcheck_enabled", True))
        except Exception:
            self._enabled = True

    def is_enabled(self) -> bool:
        return self._enabled and SPELLCHECKER_AVAILABLE

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        try:
            from opening_fenix.core.utils import get_user_dir
            cfg_path = os.path.join(get_user_dir(), "config.json")
            cfg = {}
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["spellcheck_enabled"] = bool(enabled)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not persist spellcheck_enabled state: {e}")
        self.notify_change()

    def register_listener(self, callback):
        """Registers a callback to be invoked when dictionary or enabled state changes."""
        if callable(callback):
            self._listeners.add(callback)

    def unregister_listener(self, callback):
        """Unregisters a previously registered callback."""
        self._listeners.discard(callback)

    def notify_change(self):
        """Invokes all registered callbacks to refresh highlighters."""
        for cb in list(self._listeners):
            try:
                cb()
            except Exception as e:
                logger.debug(f"Error in spellcheck listener: {e}")

    def normalize_lang(self, lang_code: Optional[str]) -> str:
        """Normalizes lang code to 'de', 'en', etc. Fallback to 'de'."""
        if not lang_code:
            return "de"
        lang = lang_code.lower().strip()
        if lang in ("auto", "all"):
            try:
                from opening_fenix.core.translation import tr
                lang = getattr(tr, "current_lang", "de")
            except Exception:
                lang = "de"
        # Take first 2 characters (e.g. en_US -> en)
        lang = lang[:2]
        return lang if lang in SUPPORTED_LANGUAGES else "de"

    def _get_checker(self, lang: str) -> Optional[SpellChecker]:
        if not SPELLCHECKER_AVAILABLE:
            return None
        lang = self.normalize_lang(lang)
        if lang not in self._checkers:
            try:
                checker = SpellChecker(language=lang)
                # Load chess terminology into the checker's frequency map
                checker.word_frequency.load_words(list(CHESS_VOCABULARY))
                if self._user_dictionary:
                    checker.word_frequency.load_words(list(self._user_dictionary))
                self._checkers[lang] = checker
            except Exception as e:
                logger.warning(f"Failed to initialize SpellChecker for language '{lang}': {e}")
                self._checkers[lang] = None
        return self._checkers[lang]

    def is_chess_token(self, token: str) -> bool:
        """Returns True if the token represents a chess move, evaluation symbol, or chess term."""
        clean = token.strip()
        if not clean:
            return True
        # Check SAN algebraic moves and evaluations
        if _SAN_PATTERN.match(clean):
            return True
        # Check predefined chess terms
        lower = clean.lower()
        if lower in CHESS_VOCABULARY:
            return True
        return False

    def is_word_valid(self, word: str, lang: str = "de") -> bool:
        """
        Validates if a word is spelled correctly or should be treated as correct
        (e.g. chess move, ignored word, user dictionary word).
        """
        if not self.is_enabled():
            return True

        if not word or not isinstance(word, str):
            return True

        clean = word.strip()
        if not clean or len(clean) <= 1:
            # Single letters like 'a' or punctuation are skipped
            return True

        # Check numbers, percentages, dates
        if re.match(r'^[\d\.,\+\-%/]+$', clean):
            return True

        lower = clean.lower()

        # Check session ignored words
        if lower in self._ignored_words:
            return True

        # Check user dictionary
        if lower in self._user_dictionary:
            return True

        # Check chess vocabulary & notation
        if self.is_chess_token(clean):
            return True

        checker = self._get_checker(lang)
        if checker is None:
            return True

        # In pyspellchecker, unknown() returns non-empty set if the word is unknown/misspelled
        if not checker.unknown([clean]):
            return True

        # If it's a hyphenated word (e.g. Caro-Kann or e4-e5), test each part
        if "-" in clean:
            parts = clean.split("-")
            if all(self.is_word_valid(p, lang) for p in parts if p):
                return True

        return False

    def get_suggestions(self, word: str, lang: str = "de", limit: int = 5) -> List[str]:
        """Returns ordered correction suggestions for a misspelled word."""
        if not SPELLCHECKER_AVAILABLE:
            return []

        if not word or not isinstance(word, str):
            return []

        clean = word.strip()
        if not clean:
            return []

        checker = self._get_checker(lang)
        if checker is None:
            return []

        try:
            candidates = checker.candidates(clean) or set()
            # Sort candidates by frequency descending so the most likely word is first
            sorted_candidates = sorted(
                candidates,
                key=lambda c: checker.word_frequency[c.lower()],
                reverse=True
            )
        except Exception as e:
            logger.debug(f"Candidate lookup error for '{word}': {e}")
            sorted_candidates = []

        suggestions: List[str] = []
        is_title = clean.istitle()
        is_upper = clean.isupper()

        for cand in sorted_candidates:
            if not cand or cand.lower() == clean.lower():
                continue
            formatted = cand
            if is_title:
                formatted = cand.capitalize()
            elif is_upper:
                formatted = cand.upper()
            if formatted not in suggestions:
                suggestions.append(formatted)
            if len(suggestions) >= limit:
                break

        return suggestions

    def add_to_user_dictionary(self, word: str):
        """Adds a word permanently to the user dictionary."""
        if not word or not isinstance(word, str):
            return
        w = word.strip().lower()
        if not w:
            return
        self._user_dictionary.add(w)
        # Update existing checkers
        for checker in self._checkers.values():
            if checker is not None:
                try:
                    checker.word_frequency.load_words([w])
                except Exception as e:
                    logger.debug(f"Could not load word '{w}' into checker: {e}")
        self._save_user_dictionary()
        self.notify_change()

    def ignore_word(self, word: str):
        """Ignores a word for the current application session."""
        if not word or not isinstance(word, str):
            return
        w = word.strip().lower()
        if w:
            self._ignored_words.add(w)
            self.notify_change()

    def is_word_ignored(self, word: str) -> bool:
        if not word or not isinstance(word, str):
            return False
        return word.strip().lower() in self._ignored_words

    @staticmethod
    def extract_words_with_spans(text: str) -> List[Tuple[str, int, int]]:
        """
        Extracts words and their character spans (start, end) from text.
        Skips markdown URLs [text](url) and punctuation at word edges.
        """
        results: List[Tuple[str, int, int]] = []
        if not text:
            return results

        # Simple word token pattern matching unicode letters, numbers and hyphens
        for match in re.finditer(r'[^\s\.,;:!?\(\)\[\]\{\}"\'`«»„“”\<\>\\\/]+', text):
            token = match.group()
            start = match.start()
            end = match.end()

            # Strip leading/trailing non-word symbols like - or _
            stripped = token.strip("-_#*~`")
            if not stripped:
                continue

            # Adjust spans
            start_offset = token.find(stripped)
            token_start = start + start_offset
            token_end = token_start + len(stripped)

            results.append((stripped, token_start, token_end))

        return results


# Global singleton access
_global_service: Optional[SpellCheckService] = None

def get_spellcheck_service() -> SpellCheckService:
    global _global_service
    if _global_service is None:
        _global_service = SpellCheckService.get_instance()
    return _global_service
