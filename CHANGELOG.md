# Changelog

All notable changes to this project will be documented in this file.

## [2.4.0] - 2026-04-15

### Fixed
- **Critical Session Handling**: Resolved `IllegalStateChangeError` during application teardown by ensuring SQLAlchemy sessions are closed only after active commits are finalized.
- **Data Integrity (Meta Utils)**: Fixed a bug in `meta_utils.py` where `None` values were being incorrectly serialized as the string `"None"`, causing logic errors in coverage calculations.
- **PGN Import Crash**: Fixed an `IndexError` in the PGN import service that occurred when parsing malformed files with empty NAG (Annotation) sets.
- **Dynamic Repair Logic**: Enhanced `repair_service.py` to trace repertoire levels through both parent and child moves, ensuring side-lines are correctly categorized during mass-repairs.
- **Engine Configuration**: Updated `EngineThread` to safely handle modern Stockfish thread options, resolving failures in the engine test suite.
- **Lichess API Stability**: Verified and documented the backoff controller and throttling algorithms in the Lichess service for 100% compliance with API terms.
- **Test Suite Stabilization**: Fixed race conditions in `test_creator_ui.py` by correctly mocking the new asynchronous `HoleFinderThread` architecture.

## [2.3.0] - 2026-04-14

### Added
- **Database Recovery System**: Automatic detection of malformed/corrupted SQLite databases with a built-in recovery and repair mechanism.
- **Enhanced Hole Finder**:
    - **Popularity Sorting**: Suggested moves are now sorted by frequency (Lichess data) by default.
    - **Transposition Awareness**: Better handling of transpositions for structural consistency.
    - **Smart Level Consistency**: Refined logic for tracking minimum reached levels to avoid false positives.
- **Automated Repertoire Integrity**: Integrated move-linking and integrity validation directly into the PGN import workflow.
- **Candidate Table Move Counter**: Added a numeric column to the Candidate Moves table in the Creator for better traceability.
- **Repertoire Color Management**: Added ability to select and update the user's color for each repertoire (Black/White), including board flipping logic.
- **Default Level Initialization**: New repertoires now automatically start with three default levels (Grundlagen, Tiefe Theorie, Nachschlagewerk).

### Fixed
- **Repertoire Index Error**: Resolved a `TypeError` in the `add_repertoire_level` method.
- **Transposition Search Data**: Fixed the transposition finder to return full move data (UCI/SAN) for direct repertoire integration.
- **Performance Audit**: Conducted a systematic audit and optimization of database and UI rendering segments.

## [2.2.0] - 2026-04-06

### Added
- **Onboarding Guided Tour**: Interactive step-by-step walkthrough for new users and profiles to ensure a smooth start.
- **Multilingual Notation**: Full support for English and German chess notation (`Nf3` vs `Sf3`) across the entire UI.
- **Lichess Elo Import Logic**: Enhanced Elo category mapping (Low/Mid/High) for more accurate move probability calculations.
- **Micro-Animations**: Added board piece "lifting" and shadow effects for a premium feel.

### Fixed
- **Trainer Move Filtering**: Resolved a critical issue where the variation filter incorrectly handled moves across variation entry points.
- **Executable Build Stability**: Fixed `build_executable.bat` to correctly package all repertoire subfolders and sound assets.
- **Repertoire Settings Stability**: Fixed multiple crashes (TypeError/RuntimeError) related to background maintenance threads.
- **Creator Engine UI**: Simplified and polished the analysis engine settings (depth, threads, Multi-PV) for better responsiveness.
- **Notation Selection Logic**: Improved contrast and layout for the new profile creation dialog.

## [2.1.0] - 2026-04-03

### Added
- **Directory-Based Repertoire Storage**: Repertoires are now stored in dedicated subfolders (`repertoires/{name}/`) instead of flat `.db` files. 
- **Automated Repertoire Assets**: New repertoires are automatically initialized with:
  - `Model Games.pgn` for high-level example games.
  - `Typical Motives.pgn` for strategic patterns.
  - `Tactics/` folder containing `Tactics.pgn` for opening-specific puzzles.
- **Migration System**: Integrated startup logic to automatically move legacy `.db` files into the new directory structure.
- **Improved SRS Feedback**: Statistics update timer in the Trainer now uses a more robust event loop handling to ensure the Big Donut chart reflects progress immediately after a move.

### Fixed
- Resolved a critical bug where the Trainer animation would reset to the board's starting position instead of the variation entry point.
- Stabilized the test suite by resolving race conditions in `test_stats_update.py` and `test_trainer_animation_reset_fix.py`.

## [2.0.0] - 2026-03-31

### Added
- **Complete Architecture Overhaul**: Transitioned to V2 with modular `core/services/` and `core/db/` layers.
- **Glassmorphism UI**: Premium, modern interface for Login and Creator windows.
- **Lichess API Token Interface**: Dedicated settings for managing API keys and verifying connections.
- **Course Introduction Window**: Beautiful splash screen for new learners.
- **Dynamic Rating System**: Implementation of "Opening Elo" to track mastery progress.

[2.1.0]: https://github.com/felixbrunner12-lab/Opening-Fenix/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/felixbrunner12-lab/Opening-Fenix/releases/tag/v2.0.0
