# Changelog

All notable changes to this project will be documented in this file.

## [0.9.9] - 2026-09-10

### Added & Improved
- **Smooth Piece Slide Animations with OutSine Easing**: Replaced linear interpolation with high-fidelity OutSine easing curves for natural deceleration and fluid piece motion.
- **Dynamic Square-Root Distance Scaling**: Implemented adaptive move animation durations based on Euclidean distance ($\text{scale} = 0.70 + 0.30 \cdot \sqrt{d / 2.0}$), scaling seamlessly between short 1-square pawn taps and long queen or rook slides.
- **VSync Refresh Rate Quantization**: Synchronized animation step durations directly to integer monitor refresh cycles (60Hz, 120Hz, 144Hz, 240Hz) to prevent sub-frame jitter and micro-stuttering.
- **Square Chessboard Layout & Symmetric Centering**: Auto-fitted the board container into a clean, symmetrical square layout with pixel-perfect coordinate centering.
- **N+1 Bulk SQL Optimization in Maintenance**: Replaced per-gap database queries with bulk group-by statements during repertoire gap repair, reducing database roundtrips from $O(N)$ to $O(1)$.
- **Background Worker GIL Yielding**: Added strategic thread sleeping in stats and backup workers to prevent GIL contention and ensure butter-smooth GUI responsiveness.
- **Streaming PGN File Imports**: Replaced full-file memory buffering with chunked file-handle streaming, keeping memory usage flat during large database imports.
- **Batched Qt UI Repaints**: Added `setUpdatesEnabled` batching across candidate move trees and analysis tables in the Creator interface for instantaneous position navigation.

## [0.9.8] - 2026-09-08

### Added & Improved
- **Profile-Specific Trainer Settings Routing**: Trainer settings adjusted from the Creator mode or standalone settings dialog now automatically resolve and route to the most recently active user profile instead of only persisting to global configuration.
- **Active Profile Resolution**: Added intelligent profile resolution hierarchy inspecting active sessions, `last_profile`, `auto_login_profile`, and recent profile activity timestamps.
- **Dynamic Profile Headers**: Settings dialog titles and sidebar navigation headers now display the resolved user profile name (e.g. `🎯 TRAINER-EINSTELLUNGEN (Felix)` or translated `Freies Training`) instead of `(Default)`.
- **Automated Profile Routing Tests**: Added comprehensive test coverage verifying profile resolution fallbacks and persistence routing.

## [0.9.7] - 2026-09-05

### Added & Improved
- **Unified Settings Architecture**: Consolidated disparate settings dialogs into a single, modern modal with an expandable/collapsible 4-tier navigation sidebar (Global Settings, Help & FAQ, Trainer Settings, Creator Settings).
- **Lichess Fair Play Lockout**: Integrated live game detection with a non-intrusive notification system and overlay that temporarily disables the course creator during active rated Lichess games.
- **Contextual Navigation & Header Bars**: Modal automatically opens to the relevant section (Trainer vs. Creator) based on launch context, and smartly hides course selectors on batch maintenance.
- **Dynamic Repertoire Statistics**: Added asynchronous loading of Lichess priority score coverage counts (`Positionen mit Prio-Score`) and engine evaluation depth ranges in Repertoire Identity.
- **Level Structure Table Dynamic Sizing**: Ensured all level rows and headers are fully visible without vertical cutoff across DPI scaling factors.
- **Card Styling Polish**: Cleaned up white box background artifacts on inactive repertoire cards for a smooth, uniform grey overlay.
- **Full German Localization Parity**: Complete German translations across all settings tabs, navigation items, tooltips, and action buttons with English fallbacks.

## [0.9.6] - 2026-08-31

### Added & Improved
- **Modern Level Selector UI**: Replaced native platform combo box controls with a modern chevron SVG indicator, refined padding, and subtle focus/hover states across dialogs and cards.
- **Dynamic Level Target Elo Display**: Repertoire configuration cards in Settings now display the target rating (Ziel-Elo) for the currently selected level, updating dynamically upon selection change.
- **Dialog Styling Polish**: Standardized drop-down arrow appearance across all application dialogs (Free Training, Settings, Repo Configuration).

## [0.9.5] - 2026-08-26

### Added
- **High-FPS Animation Pipeline**: Implemented static board snapshot caching (`_board_snapshot`) during piece slides, reducing per-frame draw calls from ~120 to 2 for ultra-smooth 60–144Hz animations.
- **Hardware Refresh Rate Auto-Detection**: Board animation timer automatically queries monitor capabilities to run animations natively at high refresh rates (120Hz/144Hz/240Hz).
- **Animation Performance Telemetry**: Added frame timing calculations, debug HUD mode, and automatic low-FPS warning heuristic logging.

### Fixed & Improved
- **Creator Toolbar Alignment**: Fixed vertical centering and padding for the active repertoire glass pill button across high-DPI scaling factors.
- **Notation Reveal Synchronization**: Synchronized move notation revealing in training mode to prevent premature move spoilers before the piece slide animation finishes.
- **Installer Build Script Robustness**: Added safe recursive directory cleanup (`safe_rmtree`) with Windows read-only attribute handling.

### Tested & Quality
- **Animation & UI Test Suites**: Added new automated unit tests in `test_animation_fps.py` and `test_creator_toolbar_repo_btn.py` with 100% pass rate.

## [0.9.4] - 2026-08-22

### Fixed
- **Multilingual Comment Autosave**: Fixed an issue where comments edited in English or other non-German languages defaulted to German during autosave due to missing `target_lang` propagation.
- **Immediate Language Switch Persistence**: Resolved a bug where deleting a comment and immediately switching languages restored stale database state or raised false missing-translation warnings.
- **Comment State Synchronization**: Consolidated redundant `on_details_changed` handlers in Creator Window to synchronize multilingual in-memory structures with UI changes in real-time.

### Tested & Quality
- **Automated UI Coverage**: Added comprehensive test cases in `test_creator_ui.py` covering multilingual comment saving, language switching, and comment deletion.

## [0.9.3] - 2026-08-20

### Fixed
- **Settings Dialog Stability**: Added top-level `sip` import and resolved runtime `NameError` exceptions during background statistics loading.
- **Comment Stats & Elo Display**: Fixed missing import dependencies (`get_elo_display`, `get_repertoire_comment_stats`) in settings dialog.
- **Checksum Calculation**: Updated `compute_repertoire_checksum` SQL queries to align with Schema V2 tables (`positions`, `moves`, and `repertoire_moves`).
- **SQLAlchemy 2.0 Compatibility**: Resolved deprecation coercion warnings in `repair_service.py` using `subq.select()`.
- **Public Build Filtering**: Enforced example course filtering in public distributions via `filter_repertoires_by_build_type`.

### Tested & Quality
- **Test Suite Expansion**: Added 16 new unit and widget interaction tests across `update_dialog`, `repertoire_tabs`, `training_center`, `tree_navigation_service`, and `board_widget` with 100% pass rate (452 passing tests).

## [0.9.1] - 2026-08-10

### Added
- **PGN Import Comment Language Selection**: PGN import (file import & text paste) now prompts the user to select both Target Level and Comment Language (e.g. DE, EN, ES, FR, IT, RU, or Auto).
- **Source Comment Deletion (Move Mode)**: Added option in Comment Transfer dialog to delete source language comments after transferring to a new target language.
- **Dedicated Repertoire Tools Container**: Relocated "Kommentare übertragen" (Transfer Comments) from Repertoire Data to a dedicated container section inside Repertoire Tools.

### Fixed
- **Full Localization & Translation Parity**: Fixed untranslated UI elements across Comment Transfer and PGN import dialogs, progress bars, and status notifications in both German and English.

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

[2.1.0]: https://github.com/Takais-Chess/Opening-Fenix/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/Takais-Chess/Opening-Fenix/releases/tag/v2.0.0
