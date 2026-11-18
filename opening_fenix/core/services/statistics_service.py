import os
import json
import sqlite3
import collections
import datetime
import threading
from typing import Dict, Any, Optional, List
from opening_fenix.core.utils import get_repertoire_db_path, get_user_dir, is_free_training_profile
from opening_fenix.core.logger import logger
from opening_fenix.core.translation import tr_ui

_GRAPH_CACHE_LOCK = threading.Lock()
_GRAPH_CACHE: collections.OrderedDict = collections.OrderedDict()
_MAX_GRAPH_CACHE = 4

_BOX_WEIGHTS = {
    0: 0.0,
    1: 0.20,
    2: 0.40,
    3: 0.65,
    4: 0.85,
    5: 1.00,
    6: 1.05,
    7: 1.10,
}


def _norm_fen4(fen: str) -> str:
    if not fen:
        return ""
    s = fen.strip()
    if s.count(" ") >= 5:
        return s.rsplit(" ", 2)[0]
    return " ".join(s.split(" ")[:4])


def _parse_dt(val: Any) -> Optional[datetime.datetime]:
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.datetime.strptime(s, fmt)
            except ValueError:
                pass
    return None


def _get_stats_graph_snapshot(db_path: str) -> Optional[Dict[str, Any]]:
    """Loads and caches a read-only repertoire graph snapshot keyed by file mtime & size."""
    try:
        st = os.stat(db_path)
        wal_path = db_path + "-wal"
        wal_st = os.stat(wal_path) if os.path.exists(wal_path) else None
        cache_key = (
            os.path.abspath(db_path),
            st.st_mtime_ns,
            st.st_size,
            wal_st.st_mtime_ns if wal_st else 0,
            wal_st.st_size if wal_st else 0,
        )
    except OSError:
        return None

    with _GRAPH_CACHE_LOCK:
        cached = _GRAPH_CACHE.get(cache_key)
        if cached is not None:
            _GRAPH_CACHE.move_to_end(cache_key)
            return cached

    with sqlite3.connect(db_path, timeout=10) as conn:
        c = conn.cursor()

        c.execute("SELECT key, value FROM metadata")
        meta = dict(c.fetchall())
        color = (meta.get('color') or 'w').lower()

        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repertoire_levels'")
        has_levels_table = (c.fetchone() is not None)
        level_defs = []
        if has_levels_table:
            c.execute('SELECT id, name, "order", target_elo FROM repertoire_levels ORDER BY "order"')
            level_defs = [
                {"id": r[0], "name": r[1], "order": r[2], "target_elo": r[3] or 1500}
                for r in c.fetchall()
            ]

        c.execute("SELECT id, fen, engine_eval FROM positions")
        pos_data = {}
        root_row = None
        min_pid = None
        for pid, fen, eval_val in c.fetchall():
            cf = _norm_fen4(fen) if fen else ""
            parts = fen.split(" ") if fen else []
            turn = parts[1].lower() if len(parts) > 1 else "w"
            pos_data[pid] = (fen, cf, turn, eval_val)
            if min_pid is None or pid < min_pid:
                min_pid = pid
            if root_row is None and fen and fen.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"):
                root_row = (pid, fen)

        c.execute("""
            SELECT m.id, m.from_position_id, m.to_position_id, m.uci, m.san, rm.level, rm.is_active
            FROM moves m
            LEFT JOIN repertoire_moves rm ON m.id = rm.move_id
        """)
        all_moves = c.fetchall()

        incoming_to_ids = set()
        rep_moves_from = collections.defaultdict(list)
        level_to_pos_sets = collections.defaultdict(set)
        all_active_to_pos = set()
        total_moves = 0
        moves_by_level = collections.defaultdict(int)
        fen_uci_to_lvl = {}
        norm_fen_uci_to_lvl = {}

        for m_id, from_id, to_id, uci, san, level, is_active in all_moves:
            if to_id is not None:
                incoming_to_ids.add(to_id)
            if is_active:
                eff_lvl = level if level is not None else 1
                total_moves += 1
                if to_id is not None:
                    all_active_to_pos.add(to_id)
                    level_to_pos_sets[eff_lvl].add(to_id)
                rep_moves_from[from_id].append({
                    "id": m_id,
                    "to_id": to_id,
                    "uci": uci,
                    "san": san,
                    "level": eff_lvl,
                })
                p_info = pos_data.get(from_id)
                if p_info is not None:
                    p_fen, p_cf, p_turn, _ = p_info
                    fen_uci_to_lvl[(p_fen, uci)] = eff_lvl
                    norm_fen_uci_to_lvl[(p_cf, uci)] = eff_lvl
                    if p_turn in ('w', 'b') and color in ('w', 'b'):
                        if p_turn == color:
                            moves_by_level[eff_lvl] += 1
                    else:
                        moves_by_level[eff_lvl] += 1
                else:
                    moves_by_level[eff_lvl] += 1

        if not root_row and pos_data:
            no_inc = [pid for pid in pos_data if pid not in incoming_to_ids]
            if no_inc:
                r_id = min(no_inc)
                root_row = (r_id, pos_data[r_id][0])
            elif min_pid is not None:
                root_row = (min_pid, pos_data[min_pid][0])

        root_positions = [pid for pid in pos_data if pid not in incoming_to_ids]
        if not root_positions and min_pid is not None:
            root_positions = [min_pid]

        level_map = {lvl: len(pset) for lvl, pset in level_to_pos_sets.items()}

    snapshot = {
        "meta": meta,
        "color": color,
        "level_defs": level_defs,
        "level_map": level_map,
        "total_positions": len(all_active_to_pos),
        "total_moves": total_moves,
        "pos_data": pos_data,
        "root_row": root_row,
        "root_positions": root_positions,
        "rep_moves_from": rep_moves_from,
        "moves_by_level": dict(moves_by_level),
        "fen_uci_to_lvl": fen_uci_to_lvl,
        "norm_fen_uci_to_lvl": norm_fen_uci_to_lvl,
    }

    with _GRAPH_CACHE_LOCK:
        _GRAPH_CACHE[cache_key] = snapshot
        _GRAPH_CACHE.move_to_end(cache_key)
        while len(_GRAPH_CACHE) > _MAX_GRAPH_CACHE:
            _GRAPH_CACHE.popitem(last=False)

    return snapshot


def calculate_repertoire_statistics(
    repo_name: str, 
    is_test: Optional[bool] = None, 
    elo_range: Optional[str] = None,
    profile_name: Optional[str] = None,
    selected_level: Optional[int] = None
) -> Dict[str, Any]:
    """
    Computes comprehensive statistics for a repertoire:
    - Level breakdown (Level 1, Level 2, Level 3, Total positions)
    - Memory load & learnability tier
    - Scope detection (e.g. specialized against 1.e4 vs full repertoire)
    - Soundness score based on Stockfish engine evaluations
    - Effectiveness (expected win rate based on Lichess database)
    - 1-step opponent coverage curve (Move 1, Move 2, Move 3...)
    """
    db_path = get_repertoire_db_path(repo_name, is_test)
    prof_data = get_profile_box_statistics(repo_name, profile_name, is_test, selected_level=selected_level) if profile_name else None
    if not os.path.exists(db_path):
        return _empty_stats_result(repo_name, profile_stats=prof_data)

    try:
        snap = _get_stats_graph_snapshot(db_path)
        if not snap:
            return _empty_stats_result(repo_name, profile_stats=prof_data)

        meta = snap["meta"]
        color = snap["color"]
        effective_elo = elo_range or meta.get('lichess_elo') or meta.get('elo') or 'mid'

        raw_level_defs = [(d["order"], d["name"]) for d in snap["level_defs"]]
        if not raw_level_defs:
            raw_level_defs = [
                (1, tr_ui("repo_settings.level_default_1", "Grundlagen")),
                (2, tr_ui("repo_settings.level_default_2", "Tiefe Theorie")),
                (3, tr_ui("repo_settings.level_default_3", "Nachschlagewerk und Erklärungen")),
            ]

        level_map = snap["level_map"]
        l1_count = level_map.get(1, 0)
        l2_count = level_map.get(2, 0)
        l3_count = level_map.get(3, 0)

        levels_list = []
        for order, name in raw_level_defs:
            cnt = level_map.get(order, 0)
            levels_list.append({
                "order": order,
                "name": name,
                "display_name": f"Level {order} (\"{name}\")",
                "count": cnt
            })

        total_positions = snap["total_positions"]
        total_moves = snap["total_moves"]
        learnability = _get_learnability_rating(total_positions, l1_count)

        pos_data = snap["pos_data"]
        root_row = snap["root_row"]
        rep_moves_from = snap["rep_moves_from"]

        if not root_row:
            return _build_stats_result(
                repo_name=repo_name,
                color=color,
                elo_range=effective_elo,
                levels_list=levels_list,
                l1=l1_count,
                l2=l2_count,
                l3=l3_count,
                total_pos=total_positions,
                total_moves=total_moves,
                learnability=learnability,
                scope={"name": tr_ui("stats.scope_full", "Gesamtes Repertoire"), "global_freq": 100.0, "is_specialized": False},
                soundness={"score": 90, "evaluated_count": 0},
                effectiveness={"win_rate": 50.0, "grade": 80},
                coverage_curve=[],
                profile_stats=prof_data
            )

        root_id, root_fen = root_row

        # Lazy Lichess JSON lookup: fetch raw JSON strings once and parse only positions visited by BFS
        raw_lichess = {}
        with sqlite3.connect(db_path, timeout=10) as conn:
            c = conn.cursor()
            c.execute("SELECT fen, moves_json FROM lichess_data WHERE elo_range = ?", (effective_elo,))
            rows = c.fetchall()
            if not rows:
                c.execute("SELECT fen, moves_json FROM lichess_data")
                rows = c.fetchall()
            for r_fen, r_json in rows:
                if r_fen and r_json:
                    clean = _norm_fen4(r_fen)
                    if clean not in raw_lichess:
                        raw_lichess[clean] = r_json

        parsed_lichess: Dict[str, dict] = {}

        def _get_ld(clean_f: str) -> dict:
            if clean_f in parsed_lichess:
                return parsed_lichess[clean_f]
            raw = raw_lichess.get(clean_f)
            if not raw:
                parsed_lichess[clean_f] = {}
                return {}
            try:
                val = json.loads(raw)
                parsed_lichess[clean_f] = val if isinstance(val, dict) else {}
            except Exception:
                parsed_lichess[clean_f] = {}
            return parsed_lichess[clean_f]

        # 5. Enhanced Scope Detection
        root_rep_moves = rep_moves_from.get(root_id, [])
        clean_root_fen = _norm_fen4(root_fen)
        root_ld = _get_ld(clean_root_fen)
        total_root_games = sum(v.get('total', 0) for v in root_ld.values())

        is_specialized = False
        scope_name = tr_ui("stats.scope_full", "Gesamtes Repertoire")
        scope_root_id = root_id
        scope_root_depth = 0
        scope_global_freq = 100.0
        in_scope_root_ucis = set()

        is_custom_root_fen = (clean_root_fen != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -")
        if is_custom_root_fen:
            fen_parts = root_fen.split(" ")
            fullmove = fen_parts[5] if len(fen_parts) >= 6 else "1"
            is_specialized = True
            scope_name = f"{tr_ui('stats.scope_start_from', 'Startstellung ab Zug')} {fullmove}"
            scope_root_id = root_id
            scope_root_depth = 0
            scope_global_freq = 100.0

        elif color == 'b':
            root_sans = {m['san'] for m in root_rep_moves}

            if len(root_rep_moves) == 1:
                curr_id = root_id
                curr_depth = 0
                trunk_moves = []
                while True:
                    outgoing = rep_moves_from.get(curr_id, [])
                    if len(outgoing) == 1:
                        m = outgoing[0]
                        p_info = pos_data.get(curr_id)
                        m_turn = p_info[2] if p_info else ('w' if curr_depth % 2 == 0 else 'b')
                        m_no = (curr_depth // 2) + 1
                        prefix = f"{m_no}." if m_turn == 'w' else f"{m_no}..."
                        trunk_moves.append(f"{prefix}{m['san']}")
                        curr_id = m['to_id']
                        curr_depth += 1
                        if curr_depth > 30:
                            break
                    else:
                        break

                if curr_depth >= 4:
                    is_specialized = True
                    scope_root_id = curr_id
                    scope_root_depth = curr_depth
                    last_moves = " ".join(trunk_moves[-2:]) if len(trunk_moves) >= 2 else trunk_moves[-1]
                    move_num = (curr_depth // 2) + 1
                    scope_name = f"{tr_ui('stats.scope_trunk_focus', 'Fokus: ab', trunk_san=last_moves)} (Zug {move_num})"
                    if total_root_games > 0 and root_rep_moves[0]['uci'] in root_ld:
                        scope_global_freq = round((root_ld[root_rep_moves[0]['uci']].get('total', 0) / total_root_games) * 100, 1)
                else:
                    m = root_rep_moves[0]
                    scope_name = f"{tr_ui('stats.scope_against', 'Gegen 1.')}{m['san']}"
                    is_specialized = True
                    scope_root_id = m['to_id']
                    scope_root_depth = 1
                    if total_root_games > 0 and m['uci'] in root_ld:
                        scope_global_freq = round((root_ld[m['uci']].get('total', 0) / total_root_games) * 100, 1)

            elif len(root_rep_moves) > 1:
                has_e4 = 'e4' in root_sans
                has_d4 = 'd4' in root_sans
                has_flanks = any(s in root_sans for s in ('c4', 'Nf3', 'f4', 'b3', 'g3'))

                if not has_e4 and (has_d4 or has_flanks):
                    is_specialized = True
                    scope_name = tr_ui("stats.scope_without_e4", "Gegen 1.d4 & Flanken (ohne 1.e4)")
                    scope_root_id = root_id
                    scope_root_depth = 0
                    in_scope_root_ucis = {m['uci'] for m in root_rep_moves}
                    if total_root_games > 0:
                        sum_cov = sum(root_ld[u].get('total', 0) for u in in_scope_root_ucis if u in root_ld)
                        scope_global_freq = round((sum_cov / total_root_games) * 100, 1)

                elif not has_d4 and has_e4 and has_flanks:
                    is_specialized = True
                    scope_name = tr_ui("stats.scope_without_d4", "Gegen 1.e4 & Flanken (ohne 1.d4)")
                    scope_root_id = root_id
                    scope_root_depth = 0
                    in_scope_root_ucis = {m['uci'] for m in root_rep_moves}
                    if total_root_games > 0:
                        sum_cov = sum(root_ld[u].get('total', 0) for u in in_scope_root_ucis if u in root_ld)
                        scope_global_freq = round((sum_cov / total_root_games) * 100, 1)

                elif has_e4 and has_d4 and has_flanks:
                    is_specialized = False
                    scope_name = tr_ui("stats.scope_full", "Gesamtes Repertoire")
                    scope_root_id = root_id
                    scope_root_depth = 0
                    scope_global_freq = 100.0
                else:
                    is_specialized = True
                    scope_name = f"Gegen 1.{', 1.'.join(sorted(root_sans))}"
                    scope_root_id = root_id
                    scope_root_depth = 0
                    in_scope_root_ucis = {m['uci'] for m in root_rep_moves}
                    if total_root_games > 0:
                        sum_cov = sum(root_ld[u].get('total', 0) for u in in_scope_root_ucis if u in root_ld)
                        scope_global_freq = round((sum_cov / total_root_games) * 100, 1)

        elif color == 'w':
            if len(root_rep_moves) == 1:
                m = root_rep_moves[0]
                scope_name = f"1.{m['san']} {tr_ui('stats.scope_repertoire', 'Repertoire')}"
                is_specialized = True
                scope_root_id = m['to_id']
                scope_root_depth = 1
                if total_root_games > 0 and m['uci'] in root_ld:
                    scope_global_freq = round((root_ld[m['uci']].get('total', 0) / total_root_games) * 100, 1)
            else:
                scope_name = tr_ui("stats.scope_full", "Gesamtes Repertoire")

        # 6. BFS Graph Traversal for Coverage Curve, Effectiveness, and Soundness
        reach_probs = {scope_root_id: 1.0}
        pos_by_ply = collections.defaultdict(list)
        bfs_queue = collections.deque([(scope_root_id, scope_root_depth)])
        visited_plies = {(scope_root_id, scope_root_depth)}

        soundness_diffs: List[float] = []
        weighted_win_score = 0.0
        total_weight_eff = 0.0

        while bfs_queue:
            curr_id, ply = bfs_queue.popleft()
            pos_by_ply[ply].append(curr_id)

            p_info = pos_data.get(curr_id)
            if not p_info or not p_info[0]:
                continue
            _fen, clean_f, turn, eval_val = p_info
            is_user_turn = (turn == color)

            rep_moves = rep_moves_from.get(curr_id, [])
            p_reach = reach_probs.get(curr_id, 0.0)

            if is_user_turn:
                ld = _get_ld(clean_f)
                for rm in rep_moves:
                    to_id = rm['to_id']
                    to_pos = pos_data.get(to_id)
                    if to_pos and to_pos[3] is not None and eval_val is not None:
                        diff = to_pos[3] - eval_val
                        loss = -diff if color == 'w' else diff
                        soundness_diffs.append(loss)

                    m_stats = ld.get(rm['uci'])
                    if m_stats:
                        w = m_stats.get('white', 0)
                        d = m_stats.get('draws', 0)
                        b = m_stats.get('black', 0)
                        tot = m_stats.get('total', 0)
                        if tot > 0:
                            user_score = (w + 0.5 * d) / tot if color == 'w' else (b + 0.5 * d) / tot
                            weighted_win_score += user_score * p_reach
                            total_weight_eff += p_reach

                    if p_reach > reach_probs.get(to_id, 0.0):
                        reach_probs[to_id] = p_reach
                    if ply < 32:
                        nxt_key = (to_id, ply + 1)
                        if nxt_key not in visited_plies:
                            visited_plies.add(nxt_key)
                            bfs_queue.append(nxt_key)
            else:
                ld = _get_ld(clean_f)
                rm_by_uci = {rm['uci'].strip().lower(): rm for rm in rep_moves}

                if curr_id == root_id and in_scope_root_ucis:
                    tot_opp_games = sum(stats.get('total', 0) for u, stats in ld.items() if u in in_scope_root_ucis)
                else:
                    tot_opp_games = sum(v.get('total', 0) for v in ld.values())

                if tot_opp_games > 0:
                    for uci, stats in ld.items():
                        u_norm = uci.strip().lower()
                        if curr_id == root_id and in_scope_root_ucis and uci not in in_scope_root_ucis:
                            continue
                        rm = rm_by_uci.get(u_norm)
                        if rm is not None:
                            to_id = rm['to_id']
                            p_next = p_reach * (stats.get('total', 0) / tot_opp_games)
                            if p_next > reach_probs.get(to_id, 0.0):
                                reach_probs[to_id] = p_next
                            if ply < 32:
                                nxt_key = (to_id, ply + 1)
                                if nxt_key not in visited_plies:
                                    visited_plies.add(nxt_key)
                                    bfs_queue.append(nxt_key)
                else:
                    if rep_moves:
                        p_next = p_reach / len(rep_moves)
                        for rm in rep_moves:
                            to_id = rm['to_id']
                            if p_next > reach_probs.get(to_id, 0.0):
                                reach_probs[to_id] = p_next
                            if ply < 32:
                                nxt_key = (to_id, ply + 1)
                                if nxt_key not in visited_plies:
                                    visited_plies.add(nxt_key)
                                    bfs_queue.append(nxt_key)

        # 7. Coverage Curve by Move
        coverage_by_move: List[Dict[str, Any]] = []
        max_ply = max(pos_by_ply.keys()) if pos_by_ply else 0
        max_full_move = (max_ply + 1) // 2

        for move_num in range(1, min(max_full_move + 1, 16)):
            target_ply = (move_num - 1) * 2 if color == 'w' else (move_num - 1) * 2 + 1
            if target_ply == 0 and is_specialized:
                cov = 100.0
            elif target_ply == 1 and is_specialized and color == 'b':
                cov = 100.0
            else:
                p_sum = sum(reach_probs.get(pid, 0.0) for pid in pos_by_ply.get(target_ply, []))
                cov = min(round(p_sum * 100.0, 1), 100.0)
            coverage_by_move.append({"move": move_num, "coverage_pct": cov})

        if soundness_diffs:
            blunders = sum(1 for loss in soundness_diffs if loss > 50)
            inacc = sum(1 for loss in soundness_diffs if 15 < loss <= 50)
            penalty = (blunders * 4.0 + inacc * 1.0) / len(soundness_diffs) * 20.0
            soundness_score = max(0, min(100, round(100 - penalty)))
        else:
            soundness_score = 92

        eff_win_rate = round((weighted_win_score / total_weight_eff) * 100, 1) if total_weight_eff > 0 else 53.5
        eff_grade = min(100, max(0, round(eff_win_rate * 1.6)))

        return _build_stats_result(
            repo_name=repo_name,
            color=color,
            elo_range=effective_elo,
            levels_list=levels_list,
            l1=l1_count,
            l2=l2_count,
            l3=l3_count,
            total_pos=total_positions,
            total_moves=total_moves,
            learnability=learnability,
            scope={
                "name": scope_name,
                "global_freq": scope_global_freq,
                "is_specialized": is_specialized
            },
            soundness={
                "score": soundness_score,
                "evaluated_count": len(soundness_diffs)
            },
            effectiveness={
                "win_rate": eff_win_rate,
                "grade": eff_grade
            },
            coverage_curve=coverage_by_move,
            profile_stats=prof_data
        )

    except Exception as e:
        logger.error(f"Error calculating repertoire statistics for {repo_name}: {e}", exc_info=True)
        return _empty_stats_result(repo_name, profile_stats=prof_data)

def _get_learnability_rating(total_positions: int, l1_count: int) -> Dict[str, Any]:
    """Evaluates the memory footprint and learnability of the repertoire."""
    if total_positions < 150:
        tier = tr_ui("stats.learn_compact", "Kompakt")
        desc = tr_ui("stats.learn_compact_desc", "Leicht zu merken, ideal für den Einstieg.")
        score = 95
    elif total_positions <= 500:
        tier = tr_ui("stats.learn_moderate", "Moderat")
        desc = tr_ui("stats.learn_moderate_desc", "Ausgewogener Umfang für Vereinsspieler.")
        score = 80
    else:
        tier = tr_ui("stats.learn_extensive", "Umfangreich")
        desc = tr_ui("stats.learn_extensive_desc", "Tiefes Meister-Repertoire mit hohem Lernaufwand.")
        score = 65

    return {
        "tier": tier,
        "score": score,
        "description": desc,
        "l1_count": l1_count,
        "total_positions": total_positions
    }

def _build_stats_result(
    repo_name: str,
    color: str,
    elo_range: str,
    levels_list: Optional[List[Dict[str, Any]]],
    l1: int,
    l2: int,
    l3: int,
    total_pos: int,
    total_moves: int,
    learnability: Dict[str, Any],
    scope: Dict[str, Any],
    soundness: Dict[str, Any],
    effectiveness: Dict[str, Any],
    coverage_curve: List[Dict[str, Any]],
    profile_stats: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return {
        "repo_name": repo_name,
        "color": color,
        "elo_range": elo_range,
        "levels": {
            "list": levels_list or [],
            "level_1": l1,
            "level_2": l2,
            "level_3": l3,
            "total_positions": total_pos,
            "total_moves": total_moves
        },
        "learnability": learnability,
        "scope": scope,
        "soundness": soundness,
        "effectiveness": effectiveness,
        "coverage_curve": coverage_curve,
        "profile_stats": profile_stats
    }

def _empty_stats_result(repo_name: str, profile_stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "repo_name": repo_name,
        "color": "w",
        "elo_range": "mid",
        "levels": {"list": [], "level_1": 0, "level_2": 0, "level_3": 0, "total_positions": 0, "total_moves": 0},
        "learnability": {"tier": tr_ui("stats.learn_compact", "Kompakt"), "score": 100, "description": "", "l1_count": 0, "total_positions": 0},
        "scope": {"name": tr_ui("stats.scope_full", "Gesamtes Repertoire"), "global_freq": 100.0, "is_specialized": False},
        "soundness": {"score": 100, "evaluated_count": 0},
        "effectiveness": {"win_rate": 50.0, "grade": 80},
        "coverage_curve": [],
        "profile_stats": profile_stats
    }

def get_available_profiles() -> List[str]:
    """Returns a sorted list of all existing user profiles."""
    profiles_dir = os.path.join(get_user_dir(), "profiles")
    if not os.path.exists(profiles_dir):
        return ["Default"]
    
    profiles = set()
    try:
        for f in os.listdir(profiles_dir):
            if f.endswith(".db"):
                profiles.add(f[:-3])
            elif f.endswith(".json") and not f.endswith("_settings.json"):
                profiles.add(f[:-5])
            elif f.endswith("_settings.json"):
                profiles.add(f[:-14])
    except Exception as e:
        logger.warning(f"Error reading profiles directory: {e}")

    filtered = [p for p in profiles if p and not p.startswith(".")]
    if not filtered:
        return ["Default"]
    return sorted(filtered, key=lambda s: s.lower())

def get_profile_box_statistics(
    repo_name: str, 
    profile_name: str, 
    is_test: Optional[bool] = None,
    selected_level: Optional[int] = None
) -> Dict[str, Any]:
    """
    Computes accurate Leitner box statistics for a specific user profile and repertoire:
    - Box distribution (Boxes 1 to 7) for reachable player moves
    - Due moves count (per box and total)
    - Unlearned moves count (total trainable player moves - learned moves)
    - Total trainable moves and mastery percentage
    - Supports level filtering (e.g. Level 1, Level 2, or All Levels)
    - Includes current profile Elo rating and active level
    """
    from opening_fenix.core.services.training_service import DEFAULT_BOX_INTERVALS

    # 1. Intervals lookup for Boxes 1-7
    box_intervals = {}
    box_intervals_short = {}
    custom_intervals = {}

    settings_path = os.path.join(get_user_dir(), "profiles", f"{profile_name}_settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                p_cfg = json.load(f)
                custom_intervals = p_cfg.get("custom_intervals", {})
        except Exception:
            pass

    for b in range(1, 8):
        val, unit = (1, "days")
        if str(b) in custom_intervals:
            entry = custom_intervals[str(b)]
            val = entry.get("value", 1)
            unit = entry.get("unit", "days")
        elif b in custom_intervals:
            entry = custom_intervals[b]
            val = entry.get("value", 1)
            unit = entry.get("unit", "days")
        else:
            val, unit = DEFAULT_BOX_INTERVALS["standard"].get(b, (1, "days"))

        short_u = "m" if "min" in unit else ("h" if "hour" in unit or "stund" in unit else ("mo" if "month" in unit or "monat" in unit else "d"))
        box_intervals_short[b] = f"{val}{short_u}"
        box_intervals[b] = f"{val} {unit}"

    box_counts = {i: 0 for i in range(1, 8)}
    box_due_counts = {i: 0 for i in range(1, 8)}
    total_trainable = 0
    total_learned = 0
    total_unlearned = 0
    total_due = 0
    learned_pct = 0.0
    is_free = is_free_training_profile(profile_name)
    active_level = 999 if is_free else 1
    current_elo = 800
    available_levels = []

    try:
        db_path = get_repertoire_db_path(repo_name, is_test)
        snap = _get_stats_graph_snapshot(db_path) if os.path.exists(db_path) else None
        if snap:
            pos_data = snap["pos_data"]
            rep_moves_from = snap["rep_moves_from"]
            color = snap["color"]
            moves_by_level = snap["moves_by_level"]
            fen_uci_to_lvl = snap["fen_uci_to_lvl"]
            norm_fen_uci_to_lvl = snap["norm_fen_uci_to_lvl"]

            # Build available_levels matching TrainingManager._get_cached_levels
            lvls = [dict(l) for l in snap["level_defs"]]
            known_orders = {l.get("order") for l in lvls if l.get("order")}
            for lvl_ord in moves_by_level:
                if lvl_ord not in known_orders:
                    lvls.append({
                        "id": lvl_ord,
                        "name": f"Level {lvl_ord}",
                        "order": lvl_ord,
                        "target_elo": 800 + 700 * lvl_ord
                    })
                    known_orders.add(lvl_ord)
            if not lvls:
                lvls = [{"id": 1, "name": "Standard", "order": 1, "target_elo": 1500}]
            lvls.sort(key=lambda x: x.get("order", 1))

            for lvl in lvls:
                ord_num = lvl.get("order", 1)
                available_levels.append({
                    "order": ord_num,
                    "name": lvl.get("name", f"Level {ord_num}"),
                    "target_elo": lvl.get("target_elo", 1500),
                    "moves": moves_by_level.get(ord_num, 0)
                })

            # Read profile TrainingData & active_level directly via sqlite3
            td_map = {}
            norm_td_map = {}
            prof_db_path = os.path.join(get_user_dir(), "profiles", f"{profile_name}.db")
            if not is_free and os.path.exists(prof_db_path):
                with sqlite3.connect(prof_db_path, timeout=10) as p_conn:
                    pc = p_conn.cursor()
                    pc.execute(
                        "SELECT active_level FROM user_repertoire_settings WHERE repertoire_name = ?",
                        (repo_name,)
                    )
                    al_row = pc.fetchone()
                    if al_row and al_row[0] is not None:
                        active_level = int(al_row[0])

                    pc.execute(
                        "SELECT fen, move_uci, box, next_due FROM training_data WHERE repertoire_name = ?",
                        (repo_name,)
                    )
                    for td_fen, td_uci, td_box, td_due_raw in pc.fetchall():
                        td_due = _parse_dt(td_due_raw)
                        td_entry = (td_box if td_box is not None else 0, td_due)
                        td_map[(td_fen, td_uci)] = td_entry
                        if td_fen:
                            norm_td_map[(_norm_fen4(td_fen), td_uci)] = td_entry

            # Compute tiered Elo matching TrainingManager.get_current_elo
            now = datetime.datetime.now()
            level_sums = {lvl.get("order", 1): 0.0 for lvl in lvls if lvl.get("order", 1) <= active_level}
            for (t_fen, t_uci), (t_box, t_due) in td_map.items():
                lvl_num = fen_uci_to_lvl.get((t_fen, t_uci))
                if lvl_num is None and t_fen:
                    lvl_num = norm_fen_uci_to_lvl.get((_norm_fen4(t_fen), t_uci))
                if lvl_num is None or lvl_num not in level_sums:
                    continue
                is_due = bool(t_due and t_due <= now)
                eff_box = max(0, t_box - 2) if is_due else t_box
                level_sums[lvl_num] += _BOX_WEIGHTS.get(eff_box, 0.0)

            elo = 800.0
            prev_target = 800.0
            for lvl in lvls:
                ord_num = lvl.get("order", 1)
                if ord_num > active_level:
                    break
                target = float(lvl.get("target_elo") or 1500)
                delta = max(50.0, target - prev_target)
                moves_in_lvl = moves_by_level.get(ord_num, 0)
                mastery = (level_sums.get(ord_num, 0.0) / moves_in_lvl) if moves_in_lvl > 0 else 0.0
                elo += delta * mastery
                prev_target = max(prev_target + 50.0, target)
            current_elo = int(round(max(800.0, elo)))

            # BFS reachability matching RepertoireNavigator.calculate_reachable_moves
            target_lvl = selected_level if selected_level is not None else 999
            root_positions = snap["root_positions"]
            queue = collections.deque(root_positions)
            visited = set(root_positions)
            reachable = []

            while queue:
                curr_id = queue.popleft()
                p_info = pos_data.get(curr_id)
                if not p_info:
                    continue
                p_fen, p_cf, p_turn, _ = p_info
                is_player = (p_turn == color)
                for rm in rep_moves_from.get(curr_id, ()):
                    to_id = rm["to_id"]
                    if is_player:
                        if rm["level"] <= target_lvl:
                            reachable.append((p_fen, p_cf, rm["uci"]))
                        if to_id not in visited:
                            visited.add(to_id)
                            queue.append(to_id)
                    else:
                        if to_id not in visited:
                            visited.add(to_id)
                            queue.append(to_id)

            lookahead = now + datetime.timedelta(minutes=5)
            for p_fen, p_cf, uci in reachable:
                entry = td_map.get((p_fen, uci)) or norm_td_map.get((p_cf, uci))
                if entry and 1 <= entry[0] <= 7:
                    box_val, next_due = entry
                    box_counts[box_val] += 1
                    total_learned += 1
                    if next_due and next_due <= lookahead:
                        box_due_counts[box_val] += 1
                        total_due += 1

            total_trainable = len(reachable)
            total_unlearned = max(0, total_trainable - total_learned)
            learned_pct = (total_learned / total_trainable * 100.0) if total_trainable > 0 else 0.0
    except Exception as e:
        logger.warning(f"Error computing box statistics for '{repo_name}' / profile '{profile_name}': {e}")

    return {
        "repo_name": repo_name,
        "profile_name": profile_name,
        "selected_level": selected_level,
        "active_level": active_level,
        "rating": current_elo,
        "available_levels": available_levels,
        "total_trainable": total_trainable,
        "total_learned": total_learned,
        "total_unlearned": total_unlearned,
        "total_due": total_due,
        "learned_pct": round(learned_pct, 1),
        "box_counts": box_counts,
        "box_due_counts": box_due_counts,
        "box_intervals": box_intervals,
        "box_intervals_short": box_intervals_short
    }

