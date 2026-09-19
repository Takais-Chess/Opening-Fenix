# 📋 Opening Fenix V2 - Feature Roadmap & Future Ideas

This document tracks planned features, community feature requests, and architectural roadmap items for Opening Fenix V2.

---

## 📌 Upcoming & Active Feature Requests

### 🌐 23. Online Version Checker
**Concept:**
Add an automatic or manual online update checker. The application contacts the GitHub repository / release API to notify the user when a newer version of Opening Fenix is available.

### ♟️ 24. Lichess Game Analysis & Repertoire Recommendations
**Concept:**
Analyze your own recent Lichess games against your active repertoire. The system will:
1. Identify the exact move where you or your opponent went "out of book".
2. Highlight any tactical or positional mistakes made after leaving the repertoire.
3. Automatically recommend whether the opponent's sideline is common enough that you should add it to your repertoire.
*(Note: Extends feature #20)*

### ♟️ 27. High-Quality Chess-Aware Comment Re-Translation
**Concept:**
Re-translate all course comments marked with `(translated)` or `(übersetzt)` using a move-masked chess translation pipeline:
1. **Move Masking**: Protect move notation (`1... e5`, `Nf3`, `6.Re1`, `Qd5`, `f6-knight`) with regex placeholders so chess symbols are never mangled.
2. **Chess Terminology Mapping**: Enforce proper chess terms (*Knight* -> *Springer*, *Bishop* -> *Läufer*, *Rook* -> *Turm*, *Pawn* -> *Bauer*, *Pin* -> *Fesselung*, *Fork* -> *Gabel*, *Castling* -> *Rochade*).
3. **Targeted Replacement**: Query only position comments where `comment` contains `(translated)` or `(übersetzt)` to replace automated machine translations with high-context, natural chess annotations.

### 🔍 29. Overthink how to add moves based from the search mode
**Concept:**
Re-evaluate and streamline how users add moves based on the search feature of finding unanalyzed popular moves ("Such Modus"):
1. **Seamless Evaluation**: Avoid clunky roundtrips between tabs; allow users to inspect candidate move evaluations, engine lines, and database stats directly in context.
2. **1-Click Level Assignment**: Allow quick addition of candidate moves directly to targeted levels (`+ L1`, `+ L2`, `+ L3`) with intelligent level suggestions.
3. **Fast-Review Workflow**: Provide a rapid step-through queue (e.g., keyboard shortcuts, add & next, skip/ignore) to efficiently process dozens of repertoire holes.

### 📊 30. Low Sample Size Indicator for Deep Lines (< 100 Games)
**Concept:**
When navigating deep into opening theory, the active database (especially Lichess Master Elo) often contains very few games (e.g., 1 to 99 games), making raw percentage frequencies statistically volatile:
1. **Header Indicator**: Place a compact `GlassPill` status badge in the Candidate Moves header between the back button (`←`) and `Show Move Arrows`.
2. **Visual States**:
   - `< 10 Games` (Critical sample): `[ 🟡 1 Game in DB ]` or `[ ⚠️ 1 Game in DB ]` with an amber accent.
   - `10 – 99 Games` (Low sample): `[ 📊 42 Games in DB ]` with a subtle warm neutral tone.
   - `≥ 100 Games`: Automatically hidden so the interface remains clean when sample size is sufficient.
3. **Contextual Tooltip**: On hover, inform the user that statistics are based on a limited game count in the active database.




---

## 🚀 Future Enhancements Roadmap

### 4. Tactic & Endgame Trainer (Prebuilt Scenarios)
- Dedicated module independent of opening repertoires for solving puzzles and practice scenarios (e.g., *"Lucena Position"*, *"Mate in 3"*).
- Isolated FEN database with tags for tactics (Pins, Forks, Endgames).

### 11. CI/CD Integration & High Test Coverage (80%+)
- GitHub Actions pipeline to run `pytest` on Windows runners for every pull request.
- Granular tests for Creator sub-tabs (Analysis, Hole Finder) and screenshot visual testing.

### 16. Custom Repertoire Cover Images
- Allow users to place a `cover.png` or `cover.jpg` inside `repertoires/{name}/` to display visual thumbnails in the Repertoire Selection grid.

### 18. Built-in Example Repertoire(s)
- Ship one or two high-quality example repertoires (e.g., *"The Italian Game - Core Lines"*) for new users to start training immediately.

### 20. Repertoire Game Analysis (Lichess API)
- Fetch recent games via Lichess API by username, filter by time control (Blitz/Rapid), and generate deviation reports.

### 21. Repertoire Schema Versioning
- Replace legacy `PRAGMA table_info` checks with a dedicated `SchemaVersion` database table for robust migrations.

### 22. Database Cleanup & Optimization
- Purge deprecated database columns (`Position.good_moves`, `Position.popularity`) identified during the v2.4.0 audit.
- Custom `DatabaseCorruptionError` handling.

---

## 📊 Completed Roadmap Items

| Item | Feature | Completion Date |
| :--- | :--- | :--- |
| **1** | **Multi-Language UI Translation (`QTranslator`)** | 2026-07-27 |
| **5** | **Glassmorphism UI & Visual Enhancements** | 2026-03-25 |
| **6** | **Performance Audit & AI Code Modularity** | 2026-04-14 |
| **8** | **Core Testing Suite & Stability (65%+ Coverage)** | 2026-03-29 |
| **9** | **User Documentation & Guides** | 2026-04-06 |
| **10** | **Lichess API Token Settings Interface** | 2026-04-02 |
| **12** | **Dynamic Rating System (Opening Elo)** | 2026-03-30 |
| **13** | **Priority-Based Level Reclassification** | 2026-04-01 |
| **15** | **Course Introduction & First-Time User Experience** | 2026-04-02 |
| **17** | **Directory-Based Repertoire Storage (`repertoires/{name}/`)** | 2026-04-03 |
| **26** | **Multilingual Repertoire Comments** | 2026-07-27 |
| **28** | **Custom Storage Directory & Cloud Sync (Google Drive / Multi-PC)** | 2026-08-19 |
| **25** | **Lichess Game Blocking (Fair Play Lockout for Creator)** | 2026-09-03 |

---
*Roadmap updated for Opening Fenix V2.*