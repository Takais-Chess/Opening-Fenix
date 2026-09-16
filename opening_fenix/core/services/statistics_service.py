import os
import json
import sqlite3
import collections
from typing import Dict, Any, Optional, List
from opening_fenix.core.utils import get_repertoire_db_path
from opening_fenix.core.logger import logger
from opening_fenix.core.translation import tr_ui

def calculate_repertoire_statistics(
    repo_name: str, 
    is_test: Optional[bool] = None, 
    elo_range: Optional[str] = None
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
    if not os.path.exists(db_path):
        return _empty_stats_result(repo_name)

    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            c = conn.cursor()
            
            # 1. Metadata
            c.execute("SELECT key, value FROM metadata")
            meta = dict(c.fetchall())
            color = (meta.get('color') or 'w').lower()
            effective_elo = elo_range or meta.get('lichess_elo') or meta.get('elo') or 'mid'

            # 2. Repertoire Level definitions & Unique Positions
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repertoire_levels'")
            has_levels_table = (c.fetchone() is not None)

            level_defs = []
            if has_levels_table:
                c.execute("SELECT `order`, `name` FROM repertoire_levels ORDER BY `order`")
                level_defs = c.fetchall()

            if not level_defs:
                level_defs = [
                    (1, tr_ui("repo_settings.level_default_1", "Grundlagen")),
                    (2, tr_ui("repo_settings.level_default_2", "Tiefe Theorie")),
                    (3, tr_ui("repo_settings.level_default_3", "Nachschlagewerk und Erklärungen")),
                ]

            c.execute("""
                SELECT rm.level, COUNT(DISTINCT m.to_position_id)
                FROM repertoire_moves rm
                JOIN moves m ON rm.move_id = m.id
                WHERE rm.is_active = 1
                GROUP BY rm.level
            """)
            level_map = dict(c.fetchall())
            l1_count = level_map.get(1, 0)
            l2_count = level_map.get(2, 0)
            l3_count = level_map.get(3, 0)

            levels_list = []
            for order, name in level_defs:
                cnt = level_map.get(order, 0)
                levels_list.append({
                    "order": order,
                    "name": name,
                    "display_name": f"Level {order} (\"{name}\")",
                    "count": cnt
                })

            c.execute("""
                SELECT COUNT(DISTINCT m.to_position_id)
                FROM repertoire_moves rm
                JOIN moves m ON rm.move_id = m.id
                WHERE rm.is_active = 1
            """)
            row_total = c.fetchone()
            total_positions = row_total[0] if row_total and row_total[0] is not None else 0

            # Count total active moves
            c.execute("SELECT COUNT(*) FROM repertoire_moves WHERE is_active = 1")
            row_moves = c.fetchone()
            total_moves = row_moves[0] if row_moves and row_moves[0] is not None else 0

            # 3. Learnability / Memory Load Rating
            learnability = _get_learnability_rating(total_positions, l1_count)

            # 4. Positions & Moves data
            c.execute("SELECT id, fen, engine_eval FROM positions")
            pos_data = {r[0]: (r[1], r[2]) for r in c.fetchall()}

            # Root position: try standard initial position first
            c.execute("SELECT id, fen FROM positions WHERE fen LIKE 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR%'")
            root_row = c.fetchone()

            if not root_row:
                # Custom start position (e.g. course starting from Move 3 or custom FEN)
                c.execute("""
                    SELECT p.id, p.fen 
                    FROM positions p
                    WHERE p.id NOT IN (
                        SELECT DISTINCT m.to_position_id 
                        FROM moves m 
                        WHERE m.to_position_id IS NOT NULL
                    )
                    ORDER BY p.id ASC
                    LIMIT 1
                """)
                root_row = c.fetchone()

            if not root_row and pos_data:
                min_id = min(pos_data.keys())
                root_row = (min_id, pos_data[min_id][0])

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
                    coverage_curve=[]
                )

            root_id, root_fen = root_row

            c.execute("""
                SELECT m.id, m.from_position_id, m.to_position_id, m.uci, m.san, rm.level, rm.is_active
                FROM moves m
                LEFT JOIN repertoire_moves rm ON m.id = rm.move_id
            """)
            all_moves = c.fetchall()

            # Lichess Data Cache
            c.execute("SELECT fen, moves_json FROM lichess_data WHERE elo_range = ?", (effective_elo,))
            lichess_cache = {}
            for r in c.fetchall():
                clean = " ".join(r[0].split(" ")[:4])
                try:
                    lichess_cache[clean] = json.loads(r[1])
                except Exception:
                    pass

            if not lichess_cache:
                c.execute("SELECT fen, moves_json FROM lichess_data")
                for r in c.fetchall():
                    clean = " ".join(r[0].split(" ")[:4])
                    if clean not in lichess_cache:
                        try:
                            lichess_cache[clean] = json.loads(r[1])
                        except Exception:
                            pass

            # Adjacency
            rep_moves_from = collections.defaultdict(list)
            for m_id, from_id, to_id, uci, san, level, is_active in all_moves:
                if is_active:
                    rep_moves_from[from_id].append({
                        "id": m_id,
                        "to_id": to_id,
                        "uci": uci,
                        "san": san,
                        "level": level
                    })

            # 5. Enhanced Scope Detection
            root_rep_moves = rep_moves_from.get(root_id, [])
            clean_root_fen = " ".join(root_fen.split(" ")[:4])
            root_ld = lichess_cache.get(clean_root_fen, {})
            total_root_games = sum(v.get('total', 0) for v in root_ld.values())

            is_specialized = False
            scope_name = tr_ui("stats.scope_full", "Gesamtes Repertoire")
            scope_root_id = root_id
            scope_root_depth = 0
            scope_global_freq = 100.0
            in_scope_root_ucis = set()

            is_custom_root_fen = (clean_root_fen != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -")
            if is_custom_root_fen:
                # Started from custom position / FEN (e.g. Move 3+)
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
                    # Single move at root: trace forward while path has only 1 active move
                    curr_id = root_id
                    curr_depth = 0
                    trunk_moves = []
                    while True:
                        outgoing = rep_moves_from.get(curr_id, [])
                        if len(outgoing) == 1:
                            m = outgoing[0]
                            m_fen = pos_data.get(curr_id, ("", None))[0]
                            m_turn = m_fen.split(" ")[1] if len(m_fen.split(" ")) > 1 else ('w' if curr_depth % 2 == 0 else 'b')
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
                        # Linear trunk line up to Move 3 or deeper before branching!
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
                        scope_root_depth = 1  # ply 1
                        if total_root_games > 0 and m['uci'] in root_ld:
                            scope_global_freq = round((root_ld[m['uci']].get('total', 0) / total_root_games) * 100, 1)

                elif len(root_rep_moves) > 1:
                    has_e4 = 'e4' in root_sans
                    has_d4 = 'd4' in root_sans
                    has_flanks = any(s in root_sans for s in ['c4', 'Nf3', 'f4', 'b3', 'g3'])

                    if not has_e4 and (has_d4 or has_flanks):
                        # Multi-root course against everything EXCEPT 1.e4
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
            visited_plies = set()

            soundness_diffs: List[float] = []
            weighted_win_score = 0.0
            total_weight_eff = 0.0

            while bfs_queue:
                curr_id, ply = bfs_queue.popleft()
                if (curr_id, ply) in visited_plies:
                    continue
                visited_plies.add((curr_id, ply))
                pos_by_ply[ply].append(curr_id)

                fen, eval_val = pos_data.get(curr_id, ("", None))
                if not fen:
                    continue
                clean_f = " ".join(fen.split(" ")[:4])
                turn = fen.split(" ")[1] if len(fen.split(" ")) > 1 else 'w'
                is_user_turn = (turn == color)

                rep_moves = rep_moves_from.get(curr_id, [])
                p_reach = reach_probs.get(curr_id, 0.0)

                if is_user_turn:
                    ld = lichess_cache.get(clean_f, {})
                    for rm in rep_moves:
                        to_pos = pos_data.get(rm['to_id'])
                        if to_pos and to_pos[1] is not None and eval_val is not None:
                            diff = to_pos[1] - eval_val
                            loss = -diff if color == 'w' else diff
                            soundness_diffs.append(loss)

                        # Human Win Rate (Lichess)
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

                        p_next = p_reach / len(rep_moves)
                        reach_probs[rm['to_id']] = reach_probs.get(rm['to_id'], 0.0) + p_next
                        if ply < 32:
                            bfs_queue.append((rm['to_id'], ply + 1))
                else:
                    ld = lichess_cache.get(clean_f, {})
                    covered_ucis = {rm['uci'].strip().lower() for rm in rep_moves}

                    if curr_id == root_id and in_scope_root_ucis:
                        tot_opp_games = sum(stats.get('total', 0) for u, stats in ld.items() if u in in_scope_root_ucis)
                    else:
                        tot_opp_games = sum(v.get('total', 0) for v in ld.values())

                    if tot_opp_games > 0:
                        for uci, stats in ld.items():
                            u_norm = uci.strip().lower()
                            if curr_id == root_id and in_scope_root_ucis and uci not in in_scope_root_ucis:
                                continue
                            if u_norm in covered_ucis:
                                p_move = stats.get('total', 0) / tot_opp_games
                                p_next = p_reach * p_move
                                for rm in rep_moves:
                                    if rm['uci'].strip().lower() == u_norm:
                                        reach_probs[rm['to_id']] = reach_probs.get(rm['to_id'], 0.0) + p_next
                                        if ply < 32:
                                            bfs_queue.append((rm['to_id'], ply + 1))
                                        break
                    else:
                        if rep_moves:
                            p_next = p_reach / len(rep_moves)
                            for rm in rep_moves:
                                reach_probs[rm['to_id']] = reach_probs.get(rm['to_id'], 0.0) + p_next
                                if ply < 32:
                                    bfs_queue.append((rm['to_id'], ply + 1))

            # 7. Coverage Curve by Move (1-step interval: Move 1, 2, 3...)
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

            # 8. Soundness Calculation
            if soundness_diffs:
                blunders = sum(1 for loss in soundness_diffs if loss > 50)
                inacc = sum(1 for loss in soundness_diffs if 15 < loss <= 50)
                penalty = (blunders * 4.0 + inacc * 1.0) / len(soundness_diffs) * 20.0
                soundness_score = max(0, min(100, round(100 - penalty)))
            else:
                soundness_score = 92

            # 9. Effectiveness Calculation
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
                coverage_curve=coverage_by_move
            )

    except Exception as e:
        logger.error(f"Error calculating repertoire statistics for {repo_name}: {e}", exc_info=True)
        return _empty_stats_result(repo_name)

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
    coverage_curve: List[Dict[str, Any]]
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
        "coverage_curve": coverage_curve
    }

def _empty_stats_result(repo_name: str) -> Dict[str, Any]:
    return {
        "repo_name": repo_name,
        "color": "w",
        "elo_range": "mid",
        "levels": {"list": [], "level_1": 0, "level_2": 0, "level_3": 0, "total_positions": 0, "total_moves": 0},
        "learnability": {"tier": tr_ui("stats.learn_compact", "Kompakt"), "score": 100, "description": "", "l1_count": 0, "total_positions": 0},
        "scope": {"name": tr_ui("stats.scope_full", "Gesamtes Repertoire"), "global_freq": 100.0, "is_specialized": False},
        "soundness": {"score": 100, "evaluated_count": 0},
        "effectiveness": {"win_rate": 50.0, "grade": 80},
        "coverage_curve": []
    }
