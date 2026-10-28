# 🚀 Opening Fenix - Performance Audit & Optimization Roadmap

*Generated: 2026-10-28 | Context Handoff & Implementation Plan*

---

## 📌 Executive Summary

A comprehensive performance audit was conducted across Opening Fenix to identify lag, UI freezes, and scaling bottlenecks. The application already implements solid architectural foundations (e.g. WAL mode, recursive CTEs for ancestor move resolution, and 2-draw-call offscreen snapshotting for piece animations). 

However, as repertoires scale to 1,000–10,000+ positions, four key areas produce noticeable latency and UI freezes:
1. **N+1 SQL query loops** in graph traversal routines.
2. **Missing composite and column indexes** on high-frequency tables.
3. **Synchronous computation on the Qt GUI main thread** (e.g. in the statistics dialog and board move handling).
4. **Artificial sleep delays & connection thrashing** on Windows.

Benchmark tests confirm that resolving these bottlenecks yields **2x to 18x speedups** in critical execution paths.

---

## 🔍 Detailed Audit & Identified Bottlenecks

### 1. Database & Persistence Layer (High Impact)

#### 1.1 N+1 Query Loop in Island Detection
- **File:** [`opening_fenix/core/services/priority_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/priority_service.py#L453-L477)
- **Method:** `detect_islands()`
- **Issue:** Inside `while queue:` BFS traversal, individual SQL queries are executed for every single visited node:
  ```python
  user_repertoire_moves = session.query(Move).join(RepertoireMove).filter(Move.from_position_id == pos_id).all()
  # else branch:
  outgoing_moves = session.query(Move).filter_by(from_position_id=pos_id).all()
  ```
  In a 3,000-position repertoire, this issues 3,000 to 6,000 individual SQL queries.
- **Benchmark:** Pre-fetching moves into an in-memory dictionary yielded an **18.4x speedup** (54.1 ms down to 2.9 ms).
- **Solution:** Pre-fetch all moves and active repertoire move IDs upfront into dictionaries before entering the BFS loop (matching the pattern used in `calculate_priority_scores`).

#### 1.2 Missing High-Frequency Indexes
- **Files:** [`opening_fenix/core/db/models.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/db/models.py) & [`opening_fenix/core/db/database.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/db/database.py#L134-L177)
- **Issues:**
  1. `TrainingData`: Queried on the hot path via `repertoire_name == repo_name AND next_due <= lookahead` (`get_stats_for_repertoire`, `get_next_move`). Needs a composite index:
     ```python
     Index('ix_training_data_repo_due', 'repertoire_name', 'next_due')
     ```
  2. `Position.analysis_depth`: Queried in `run_db_analysis` and `sync_analysis_data_from_other_repertoires`:
     `WHERE Position.analysis_depth IS NULL OR Position.analysis_depth < target_depth`
     Currently unindexed, forcing a full table scan over all positions in every repertoire.
     Needs `index=True` on `Position.analysis_depth`.
  3. `Position.is_hole_exempt`: Queried in HoleFinder without an index.

#### 1.3 Sub-Optimal SQLite PRAGMA Cache Configuration
- **File:** [`opening_fenix/core/db/database.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/db/database.py#L75-L82)
- **Issue:** SQLite defaults `PRAGMA cache_size` to `-2000` (~2 MB). Once a repertoire grows past a few hundred positions, pages are continuously evicted from RAM to disk.
- **Solution:** Add to connection pragmas:
  ```python
  dbapi_connection.execute("PRAGMA cache_size = -64000")  # 64 MB RAM cache
  dbapi_connection.execute("PRAGMA temp_store = MEMORY")   # Intermediate joins/sorts in RAM
  dbapi_connection.execute("PRAGMA mmap_size = 268435456") # 256 MB memory-mapped I/O
  ```

#### 1.4 Single-Row Queries and Updates in PGN Imports
- **File:** [`opening_fenix/core/services/import_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/import_service.py#L162-L165) & [L252-L255](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/import_service.py#L252-L255)
- **Issue:**
  1. When lowering a level for an existing move during PGN import:
     `existing_rm = session.query(RepertoireMove).filter_by(move_id=move_id).first()` runs synchronously per move inside the tree traversal loop.
  2. For NAG updates:
     `for m_id, n in moves_to_update_nag.items(): session.query(Move).filter_by(id=m_id).update({'nag': n})` executes an individual SQL update statement per move.
- **Solution:** Accumulate updates in-memory and execute batch updates via `session.bulk_update_mappings()` or a single raw SQL `UPDATE moves SET nag = CASE ...`.

---

### 2. GUI Thread & Responsiveness (High Impact)

#### 2.1 Synchronous Stats Computation Freezing GUI
- **File:** [`opening_fenix/gui/dialogs/stats_dialog.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/gui/dialogs/stats_dialog.py#L739-L744)
- **Issue:** While initial dialog loading runs on a background worker, switching the **Profile** or **Level** combo box calls:
  ```python
  def load_profile_box_statistics(self, profile_name: str, level_filter: Optional[int] = None):
      prof_data = get_profile_box_statistics(self.repo_name, profile_name, self.is_test, selected_level=level_filter)
      self.update_profile_box_ui(prof_data)
  ```
  `get_profile_box_statistics()` connects to SQLite, initializes `RepertoireManager` + `TrainingManager`, and executes a full BFS reachability traversal **directly on the Qt main thread**, freezing the window for 200–1000 ms.
- **Solution:** Execute `get_profile_box_statistics` inside a lightweight background `QThread` worker with progress or loading state.

#### 2.2 Synchronous DB Hit on Board Move Input
- **File:** [`opening_fenix/core/services/repertoire_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/repertoire_service.py#L220-L246)
- **Method:** `get_alternative_move_type()`
- **Issue:** Queries the database synchronously on every move attempt during training:
  ```python
  exists = self.repo_session.query(RepertoireMove.id).join(Move).filter(...)
  ```
  `TrainingManager` already maintains `_rep_move_cache` and `_move_by_fen_uci_cache` in RAM.
- **Solution:** Check the in-memory cache first for an instant O(1) response before touching the database session.

#### 2.3 Recursive CTE in Candidate Moves Table Render
- **File:** [`opening_fenix/creator/creator_window.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/creator/creator_window.py#L5036-L5040)
- **Issue:** In Overhaul mode, for every single candidate move displayed, it calls `self.backend.is_branch_fully_reviewed(to_pos_id, self.overhaul_start)`. Each call executes a separate recursive SQL CTE while rendering the table.
- **Solution:** Batch-fetch reviewed positions for the active session or memoize the branch status.

---

### 3. Graph Traversal & Algorithm Inefficiencies (Medium Impact)

#### 3.1 Artificial Windows Sleep Penalty in BFS Depth Calculation
- **File:** [`opening_fenix/core/services/lichess_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/lichess_service.py#L119-L121)
- **Issue:**
  ```python
  if nodes_visited % 200 == 0:
      time.sleep(0.001)  # Yield GIL periodically during BFS graph traversal
  ```
  On Windows, `time.sleep(0.001)` does not sleep for 1 ms; the standard Windows timer tick resolution is **~15.6 ms**. For 10,000 positions, this introduces **~780 ms of artificial thread sleep**.
- **Solution:** Use `time.sleep(0)` (which immediately yields the current execution slice without sleeping for a timer tick) or yield only every 2,000 nodes.

#### 3.2 Redundant SQL Query in Variation Filter Build
- **File:** [`opening_fenix/core/services/navigator_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/navigator_service.py#L28-L35)
- **Issue:** `build_variation_move_set()` receives `cache_data['pos_cache']` (which already holds all `Position` objects in memory), yet still executes `self.repertoire_manager.repo_session.query(Position.id).filter(...)`.
- **Solution:** Filter directly over `pos_cache.values()` in Python memory, eliminating the SQL round-trip.

#### 3.3 Micro-Allocations in FEN Normalization
- **Benchmark:** `" ".join(fen.split(" ")[:4])` vs `fen.rsplit(" ", 2)[0]`:
  `rsplit(" ", 2)[0]` is **2.1x faster** (9.3 ms vs 19.2 ms per 50,000 operations) with zero memory allocations for the discarded tokens.

---

### 4. Engine Analysis & Evaluation Caching (Medium Impact)

#### 4.1 Connection Thrashing in Engine Cache Service
- **File:** [`opening_fenix/core/services/engine_cache_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/engine_cache_service.py#L36-L41)
- **Issue:** On any L1 cache miss, a new SQLite connection is opened, executes two PRAGMA statements, queries, and closes. Creating/closing connections per lookup introduces heavy file-lock overhead.
- **Solution:** Use a persistent thread-local connection or keep a single long-lived read connection per thread.

#### 4.2 Dynamic String-Interpolated SQL with 1,000+ IDs
- **File:** [`opening_fenix/core/services/tree_navigation_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/tree_navigation_service.py#L39)
- **Issue:** `v_ids_sql = f"CASE WHEN id IN ({','.join(map(str, v_ids))}) THEN 1 ELSE 0 END DESC,"`
  Interpolating thousands of move IDs strains the SQLite query planner and risks hitting `SQLITE_MAX_EXPR_DEPTH`.
- **Solution:** Join against a temporary table or CTE instead of formatting thousands of literals into the query string.

---

## 🎯 Prioritized Action Plan

| Priority | Task | Target Files | Expected Gain |
| :--- | :--- | :--- | :--- |
| **P1** | **Batch queries in `detect_islands`** (eliminate N+1 loop) | [`priority_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/priority_service.py) | **~18x faster** island detection; instantaneous UI response |
| **P1** | **Add composite & missing indexes** (`TrainingData(repo, next_due)`, `Position.analysis_depth`) | [`models.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/db/models.py), [`database.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/db/database.py) | Eliminates full table scans during stats checks and analysis sync |
| **P1** | **Move `StatsDialog` level/profile switching to background thread** | [`stats_dialog.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/gui/dialogs/stats_dialog.py) | Eliminates UI freezing when interacting with the stats dialog |
| **P2** | **Tune SQLite PRAGMAs** (`cache_size=-64000`, `temp_store=MEMORY`, `mmap_size=256MB`) | [`database.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/db/database.py) | Faster queries across all features by keeping DB pages in RAM |
| **P2** | **Replace `time.sleep(0.001)` with `time.sleep(0)`** in BFS | [`lichess_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/lichess_service.py) | Eliminates up to ~800 ms of artificial lag during Lichess BFS |
| **P2** | **Batch NAG updates in PGN import** | [`import_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/import_service.py) | Faster imports on large courses with rich annotations |
| **P3** | **Reuse thread-local SQLite connection** in engine cache | [`engine_cache_service.py`](file:///c:/Users/Felix/eigene%20Programme/Opening-Fenix/Opening-Fenix/opening_fenix/core/services/engine_cache_service.py) | Reduces connection thrashing during evaluation queries |

---

## 💻 Instructions for Continuing on the Other PC

When you switch to your other computer:

1. **Pull the latest changes:**
   ```bash
   git pull origin main
   ```
2. **Open your AI Assistant / Antigravity on that PC and prompt:**
   > *"I pulled the latest changes from GitHub. Please read `PERFORMANCE_ROADMAP.md` and let's start implementing the P1 performance improvements (batch queries in detect_islands, missing indexes in models/database, and async profile loading in stats_dialog)."*
3. All context, file paths, benchmark data, and the prioritized roadmap are self-contained in this repository file!
