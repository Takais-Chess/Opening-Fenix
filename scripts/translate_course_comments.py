import os
import sys
import json
import sqlite3
import time
import urllib.request
import urllib.parse
import re

# Add project root to sys.path
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_dir)

from opening_fenix.core.services.backup_service import create_repertoire_backup
from opening_fenix.core.utils import (
    get_multilingual_comment_dict,
    parse_pgn_tagged_comment,
    format_multilingual_comment,
    get_repertoire_comment_stats
)
from opening_fenix.core.logger import logger

DELIMITER = "\n<<<SEP>>>\n"

# Global memory caches to avoid translating identical text strings repeatedly
translation_cache_de_to_en = {}
translation_cache_en_to_de = {}
lang_detect_cache = {}

def detect_language(text: str) -> str:
    """
    Detects if text is German ('de') or English ('en').
    Uses heuristic fast-path first, falling back to Google Translate API.
    """
    if not text or not text.strip():
        return 'de'
    
    clean_text = text.strip()
    if clean_text in lang_detect_cache:
        return lang_detect_cache[clean_text]
        
    # Heuristic fast checks
    german_indicators = ['ä', 'ö', 'ü', 'ß', 'Ä', 'Ö', 'Ü', 'Zug', 'Schwarz', 'Weiß', 'Bauer', 'Springer', 'Läufer', 'Turm', 'Dame', 'König', 'Stellung', 'Variante', 'Rochade', 'rochieren']
    for ind in german_indicators:
        if ind in clean_text:
            lang_detect_cache[clean_text] = 'de'
            return 'de'
            
    # API Detection via Google GTX
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=en&dt=t&q=" + urllib.parse.quote(clean_text)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            detected = res[2] if len(res) > 2 and isinstance(res[2], str) else 'en'
            lang = 'de' if detected.lower().startswith('de') else 'en'
            lang_detect_cache[clean_text] = lang
            return lang
    except Exception:
        lang_detect_cache[clean_text] = 'en'
        return 'en'


def translate_single(text: str, source_lang: str, target_lang: str) -> str:
    """Translates a single text string using Google Translate GTX endpoint."""
    if not text or not text.strip():
        return text
        
    clean_text = text.strip()
    cache = translation_cache_de_to_en if source_lang == 'de' else translation_cache_en_to_de
    if clean_text in cache:
        return cache[clean_text]
        
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q=" + urllib.parse.quote(clean_text)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                translated = ''.join([part[0] for part in res[0] if part and part[0]]).strip()
                cache[clean_text] = translated
                return translated
        except Exception as e:
            time.sleep(0.5 * (attempt + 1))
            
    cache[clean_text] = clean_text
    return clean_text


def translate_batch(texts: list[str], source_lang: str, target_lang: str) -> list[str]:
    """Translates a list of texts in batch mode to maximize efficiency."""
    if not texts:
        return []
        
    cache = translation_cache_de_to_en if source_lang == 'de' else translation_cache_en_to_de
    
    # Check cache for all texts
    missing_indices = []
    missing_texts = []
    results = [None] * len(texts)
    
    for i, t in enumerate(texts):
        clean_t = t.strip()
        if clean_t in cache:
            results[i] = cache[clean_t]
        else:
            missing_indices.append(i)
            missing_texts.append(clean_t)
            
    if not missing_texts:
        return results
        
    # Translate missing texts in chunks of up to 25 items
    chunk_size = 25
    for chunk_start in range(0, len(missing_texts), chunk_size):
        chunk_indices = missing_indices[chunk_start:chunk_start + chunk_size]
        chunk_texts = missing_texts[chunk_start:chunk_start + chunk_size]
        
        combined = DELIMITER.join(chunk_texts)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q=" + urllib.parse.quote(combined)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        
        success = False
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res = json.loads(resp.read().decode('utf-8'))
                    full_trans = ''.join([part[0] for part in res[0] if part and part[0]])
                    parts = full_trans.split("<<<SEP>>>")
                    cleaned_parts = [p.strip() for p in parts]
                    
                    if len(cleaned_parts) == len(chunk_texts):
                        for orig, trans, idx in zip(chunk_texts, cleaned_parts, chunk_indices):
                            cache[orig] = trans
                            results[idx] = trans
                        success = True
                        break
                    else:
                        break
            except Exception:
                time.sleep(0.5 * (attempt + 1))
                
        if not success:
            # Fallback to single requests for this chunk
            for orig, idx in zip(chunk_texts, chunk_indices):
                trans = translate_single(orig, source_lang, target_lang)
                results[idx] = trans
                
        time.sleep(0.1)  # Throttling between batch calls
        
    return results


def process_repertoire_comments(repo_name: str, db_path: str):
    """
    Backs up and translates all missing comments for a single repertoire database.
    """
    print(f"\n==========================================")
    print(f" Processing Course: '{repo_name}'")
    print(f"==========================================")
    
    # 1. Create Pre-Translation Backup
    print(f"Creating pre-translation backup for '{repo_name}'...")
    backup_path = create_repertoire_backup(repo_name, trigger_type="pre_translation_backup")
    if backup_path:
        print(f"  Backup created successfully: {os.path.basename(backup_path)}")
    else:
        print(f"  Note: Backup check returned existing snapshot or skipped.")
        
    # 2. Connect to SQLite database
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    c.execute("SELECT id, comment FROM positions WHERE comment IS NOT NULL AND comment != ''")
    rows = c.fetchall()
    
    total_comments = len(rows)
    print(f"Found {total_comments} commented positions in database.")
    
    if total_comments == 0:
        conn.close()
        return
        
    # Prepare batch translation jobs
    # Jobs to update: list of (pos_id, de_text, en_text)
    update_jobs = []
    
    de_to_en_batch = []
    de_to_en_metadata = [] # (pos_id, de_text)
    
    en_to_de_batch = []
    en_to_de_metadata = [] # (pos_id, en_text)
    
    already_complete = 0
    
    for pos_id, raw_comment in rows:
        raw = raw_comment.strip()
        
        # Check PGN tags first
        pgn_tagged = parse_pgn_tagged_comment(raw)
        if pgn_tagged:
            comment_dict = pgn_tagged
        else:
            comment_dict = get_multilingual_comment_dict(raw)
            
        de_val = comment_dict.get('de', '').strip()
        en_val = comment_dict.get('en', '').strip()
        
        if de_val and en_val:
            already_complete += 1
            continue
            
        if de_val and not en_val:
            de_to_en_batch.append(de_val)
            de_to_en_metadata.append((pos_id, de_val))
        elif en_val and not de_val:
            en_to_de_batch.append(en_val)
            en_to_de_metadata.append((pos_id, en_val))
        else:
            # Plain text string without JSON keys
            detected_lang = detect_language(raw)
            if detected_lang == 'de':
                de_to_en_batch.append(raw)
                de_to_en_metadata.append((pos_id, raw))
            else:
                en_to_de_batch.append(raw)
                en_to_de_metadata.append((pos_id, raw))
                
    print(f"  - Already bilingual: {already_complete}")
    print(f"  - Needs DE -> EN translation: {len(de_to_en_batch)}")
    print(f"  - Needs EN -> DE translation: {len(en_to_de_batch)}")
    
    # 3. Perform batch translations
    if de_to_en_batch:
        print(f"  Translating {len(de_to_en_batch)} comments from German to English...")
        en_translations = translate_batch(de_to_en_batch, 'de', 'en')
        for (pos_id, de_text), en_trans in zip(de_to_en_metadata, en_translations):
            # Append suffix
            en_final = f"{en_trans} (translated)"
            new_json = json.dumps({"de": de_text, "en": en_final}, ensure_ascii=False)
            update_jobs.append((new_json, pos_id))
            
    if en_to_de_batch:
        print(f"  Translating {len(en_to_de_batch)} comments from English to German...")
        de_translations = translate_batch(en_to_de_batch, 'en', 'de')
        for (pos_id, en_text), de_trans in zip(en_to_de_metadata, de_translations):
            # Append suffix
            de_final = f"{de_trans} (übersetzt)"
            new_json = json.dumps({"de": de_final, "en": en_text}, ensure_ascii=False)
            update_jobs.append((new_json, pos_id))
            
    # 4. Save to Database
    if update_jobs:
        print(f"  Writing {len(update_jobs)} updated position comments to database...")
        c.executemany("UPDATE positions SET comment = ? WHERE id = ?", update_jobs)
        conn.commit()
        print(f"  Updated database successfully!")
    else:
        print(f"  No database updates needed.")
        
    conn.close()


def main():
    repo_base_dir = os.path.join(project_dir, "repertoires")
    if not os.path.exists(repo_base_dir):
        print(f"Repertoires directory not found at: {repo_base_dir}")
        return
        
    repertoires = [r for r in sorted(os.listdir(repo_base_dir)) if os.path.isdir(os.path.join(repo_base_dir, r))]
    
    print(f"Starting course comment translation for {len(repertoires)} courses...")
    
    start_time = time.time()
    for repo_name in repertoires:
        db_path = os.path.join(repo_base_dir, repo_name, f"{repo_name}.db")
        if os.path.exists(db_path):
            process_repertoire_comments(repo_name, db_path)
            
    elapsed = time.time() - start_time
    print(f"\n==========================================")
    print(f" All courses successfully processed in {elapsed:.2f}s!")
    print(f"==========================================")


if __name__ == "__main__":
    main()
