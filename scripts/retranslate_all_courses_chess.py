import os
import sys
import json
import sqlite3
import re
import urllib.request
import urllib.parse
import time

project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_dir)

from opening_fenix.core.services.backup_service import create_repertoire_backup
from opening_fenix.core.utils import get_multilingual_comment_dict

MOVE_PATTERNS = [
    r'\b[1-9][0-9]*\.\.\.[a-h1-8O\-]+\b',
    r'\b[1-9][0-9]*\.[a-h1-8O\-]+\b',
    r'\bO-O-O\b', r'\bO-O\b',
    r'\b[KQRBNSLTD]?[a-h]?[1-8]?x?[a-h][1-8]\b',
    r'\b[a-h][1-8]-[a-h][1-8]\b',
    r'\b[fKQRBNSLTD][1-8]-[fKQRBNSLTD][1-8]\b'
]
COMBINED_MOVE_REGEX = '|'.join(MOVE_PATTERNS)

def mask_moves(text):
    moves = []
    def repl(m):
        moves.append(m.group(0))
        return f" XMOVE{len(moves)-1}X "
    masked = re.sub(COMBINED_MOVE_REGEX, repl, text)
    return masked, moves

def unmask_moves(text, moves, target_lang):
    for i, m in enumerate(moves):
        ger_m = m
        if target_lang == 'de':
            # English -> German SAN (N->S, B->L, R->T, Q->D, K->K)
            ger_m = re.sub(r'(\b|\.)N', r'\1S', ger_m)
            ger_m = re.sub(r'(\b|\.)B', r'\1L', ger_m)
            ger_m = re.sub(r'(\b|\.)R', r'\1T', ger_m)
            ger_m = re.sub(r'(\b|\.)Q', r'\1D', ger_m)
        else:
            # German -> English SAN (S->N, L->B, T->R, D->Q, K->K)
            ger_m = re.sub(r'(\b|\.)S', r'\1N', ger_m)
            ger_m = re.sub(r'(\b|\.)L', r'\1B', ger_m)
            ger_m = re.sub(r'(\b|\.)T', r'\1R', ger_m)
            ger_m = re.sub(r'(\b|\.)D', r'\1Q', ger_m)
            
        text = re.sub(rf'\s*XMOVE{i}X\s*', f" {ger_m} ", text)
    return re.sub(r'\s+', ' ', text).strip()


def translate_chess_text(text, source_lang, target_lang):
    if not text or not text.strip():
        return ""
        
    masked, moves = mask_moves(text.strip())
    
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_lang}&tl={target_lang}&dt=t&q=" + urllib.parse.quote(masked)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    
    translated_raw = masked
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                translated_raw = ''.join([part[0] for part in res[0] if part and part[0]]).strip()
                break
        except Exception:
            time.sleep(0.3 * (attempt + 1))
            
    final_text = unmask_moves(translated_raw, moves, target_lang)
    
    if target_lang == 'de':
        replacements = [
            (r"\bVerlobte\b", "Fianchetto"),
            (r"\bVerlobte vervollständigt\b", "Fianchetto aufbaut"),
            (r"\bSpringer seiner Königin\b", "Damenspringer"),
            (r"\bSpringer seines Königs\b", "Königsspringer"),
            (r"\bKönigin-Springer\b", "Damenspringer"),
            (r"\bKönig-Springer\b", "Königsspringer"),
            (r"\bKönigin\b", "Dame"),
            (r"\bKöniginnen\b", "Damen"),
            (r"\bRitter\b", "Springer"),
            (r"\bRittern\b", "Springern"),
            (r"\bBischof\b", "Läufer"),
            (r"\bBischöfe\b", "Läufer"),
            (r"\bBischöfen\b", "Läufern"),
            (r"\bKrähe\b", "Turm"),
            (r"\bKrähen\b", "Türme"),
            (r"\bSchritt\b", "Zug"),
            (r"\bSchritte\b", "Züge"),
            (r"\bUmzug\b", "Zug"),
            (r"\bUmzüge\b", "Züge"),
            (r"\bFortschritt für den Platzgewinn\b", "wichtiger Raumgewinn-Zug"),
            (r"\bPlatzgewinn-Vormarsch\b", "Raumgewinn-Zug"),
            (r"\bTabiya\b", "Schlüsselstellung"),
            (r"\bTabiyas\b", "Schlüsselstellungen"),
            (r"\btransponiert zu\b", "leitet über in"),
            (r"\btransponieren zu\b", "übergehen in"),
            (r"\bintoLine\b", "in Variante"),
            (r"\binto Line\b", "in Variante"),
            (r"\bLinie\b", "Variante"),
        ]
        for pat, rep in replacements:
            final_text = re.sub(pat, rep, final_text, flags=re.IGNORECASE)
    else:
        replacements = [
            (r"\bknight of his queen\b", "queen's knight"),
            (r"\bknight of his king\b", "king's knight"),
            (r"\bengaged\b", "fianchetto"),
            (r"\bstep\b", "move"),
            (r"\bsteps\b", "moves"),
            (r"\brelocation\b", "move"),
            (r"\bkey space gain advance\b", "key space-gaining advance"),
        ]
        for pat, rep in replacements:
            final_text = re.sub(pat, rep, final_text, flags=re.IGNORECASE)
            
    return final_text


def process_course(repo_name, db_path):
    print(f"\n==========================================")
    print(f" Retranslating Course: '{repo_name}'")
    print(f"==========================================")
    
    # Pre-execution safety backup
    create_repertoire_backup(repo_name, trigger_type="pre_chess_llm_retranslation")
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, comment FROM positions WHERE comment IS NOT NULL AND comment != '' ORDER BY id")
    rows = c.fetchall()
    
    total = len(rows)
    print(f"Found {total} commented positions.")
    if total == 0:
        conn.close()
        return
        
    updates = []
    start_t = time.time()
    
    # Deduplication cache for memory speedup
    cache_de = {}
    cache_en = {}
    
    for i, (pos_id, raw) in enumerate(rows):
        cd = get_multilingual_comment_dict(raw)
        
        de_t = cd.get('de', '').strip()
        en_t = cd.get('en', '').strip()
        
        # Determine original vs translated
        # If de ends with (übersetzt) -> original was EN
        # If en ends with (translated) -> original was DE
        if de_t.endswith('(übersetzt)') or (en_t and not de_t):
            # Clean original EN text (strip tag if present)
            orig_en = en_t.replace('(translated)', '').strip()
            
            if orig_en in cache_de:
                de_chess = cache_de[orig_en]
            else:
                de_chess = translate_chess_text(orig_en, 'en', 'de')
                cache_de[orig_en] = de_chess
                
            de_final = f"{de_chess} (übersetzt)"
            new_json = json.dumps({"de": de_final, "en": orig_en}, ensure_ascii=False)
            updates.append((new_json, pos_id))
            
        elif en_t.endswith('(translated)') or (de_t and not en_t):
            orig_de = de_t.replace('(übersetzt)', '').strip()
            
            if orig_de in cache_en:
                en_chess = cache_en[orig_de]
            else:
                en_chess = translate_chess_text(orig_de, 'de', 'en')
                cache_en[orig_de] = en_chess
                
            en_final = f"{en_chess} (translated)"
            new_json = json.dumps({"de": orig_de, "en": en_final}, ensure_ascii=False)
            updates.append((new_json, pos_id))
            
        if (i + 1) % 100 == 0 or (i + 1) == total:
            print(f"  Processed {i+1}/{total} positions... ({time.time() - start_t:.1f}s)")
            
    if updates:
        c.executemany("UPDATE positions SET comment = ? WHERE id = ?", updates)
        conn.commit()
        print(f"Successfully updated {len(updates)} position comments for '{repo_name}' in {time.time() - start_t:.2f}s!")
    else:
        print(f"No updates needed for '{repo_name}'.")
        
    conn.close()


def main():
    repo_base_dir = os.path.join(project_dir, "repertoires")
    repertoires = [r for r in sorted(os.listdir(repo_base_dir)) if os.path.isdir(os.path.join(repo_base_dir, r))]
    
    print(f"Starting chess-aware retranslation across {len(repertoires)} courses...")
    start_t = time.time()
    
    for repo_name in repertoires:
        db_path = os.path.join(repo_base_dir, repo_name, f"{repo_name}.db")
        if os.path.exists(db_path):
            process_course(repo_name, db_path)
            
    print(f"\n==========================================")
    print(f" All courses successfully retranslated in {time.time() - start_t:.2f}s!")
    print(f"==========================================")

if __name__ == "__main__":
    main()
