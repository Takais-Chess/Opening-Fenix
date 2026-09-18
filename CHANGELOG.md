# Changelog
 
All notable changes to this project will be documented in this file.
 
## [1.0.0] - 2026-09-18
 
### Added & Improved
- **Official 1.0 Production Release**: Comprehensive chess opening repertoire manager and active recall training system.
- **High-DPI Scaling Polish**: Conducted an end-to-end visual audit and layout optimization across all 12 core application windows and dialogs under high-DPI scaling (125%, 150%, 200%).
- **Engine Action Dialog**: Fixed fixed-width layout clipping by adopting dynamic DPI scaling (`scale()`) and minimum size constraints (`SetMinimumSize`), ensuring full visibility for action buttons.
- **Course Import Dialog**: Optimized headline typography, letter-spacing, and dialog dimensions to prevent button bar and header text overlap.
- **Repertoire Selection Modal**: Scaled dimensions to `800x640`, refined button typography and padding, and removed horizontal scrollbar clutter.
- **Creator Window Layout Hardening**: Polished Analysis tab with adaptive column sizing, smart percentage formatting, compact engine configuration, and streamlined Transposition tab toolbar.
- **Repertoire Statistics & Insights**: Refined modal dimensions and level card padding to prevent description text clipping under 1.5x scaling.
- **Export Dialog**: Enhanced minimum width to prevent truncation of export format descriptions and button rows.
- **Localization Parity**: 100% German and English key parity across all 1,166 translation keys.
- **Quality Assurance**: 704 automated test cases passing across database operations, UI flows, and transposition scanners.

## [0.9.13] - 2026-09-16
 
### Added & Improved
- **Repertoire Statistics & Insights**: Introduced a dedicated Statistics modal accessible directly from the Creator toolbar (right of the Resources button).
- **Opening Scope Detection**: Smart root branch detection (e.g. `Gegen 1.e4`, `1.d4 Repertoire`) that scopes coverage curves and expected win rates specifically within the course's focus, eliminating false alerts for out-of-scope openings.
- **3 Core Metric Badges**: Real-world Lichess expected win rate (Effectiveness), Stockfish path evaluation score (Soundness), and memory load categorization (Learnability).
- **1-Step Move Coverage Curve**: Dynamic step-by-step opponent coverage curve tracking book survival rate per move with colored visual indicators.
- **Clean Level Sizing Breakdown**: Non-cluttered text breakdown of unique positions across Level 1 (Core), Level 2 (Expanded), and Level 3 (Deep).
- **2-Move Transposition Scanner Speed & Quality Overhaul**: Fixed engine depth variable shadowing bug that caused runaway engine analysis on deep lines, tuned tolerance to 10 centipawns (`🟡 Solide (-X cp)`) accepting practical transposition moves alongside top engine moves, implemented lazy SAN computation, and added detailed real-time logging.
- **Transposition Scan System Responsiveness**: Prevented full system freezing during deep multi-move scans by dynamically reserving at least 1 CPU core for the OS and UI, and inserting GIL yields between evaluations, with engine analysis driven strictly by the configured search depth.
- **Batch Maintenance & Trainer Fluidity**: Throttled high-frequency progress signals (250ms) during Lichess imports to prevent flooding the Qt event loop, released SQLite write transactions before network rate-limit waits, and introduced cooperative GIL yielding and low background thread priority to ensure butter-smooth Trainer board animations.

## [0.9.12] - 2026-09-15
 
### Added & Improved
- **Enhanced 2-Move Transposition Detection**: Refined transposition search logic to permit valid sibling branch transpositions of equal ply depth and hardened internal SAN move generation.
- **Smart Promotion & Underpromotion Filtering**: Filtered out underpromotions (`=R`, `=B`, `=N`) and promotion sequences where the promoted piece is immediately captured on the next half-move from both global and local transposition scanners.
- **Course Import & Multi-Profile Synchronization**: Added robust PGN course import service with interactive dialog, native window close event filtering, and multi-profile course management.
- **Lichess Explorer & Priority Score Hardening**: Improved Lichess data synchronization, priority calculations, and error resilience during background data retrieval.
- **Installer & Build Automation**: Hardened installer build pipeline with safe directory deletion and automatic process termination for locked binaries.
 
## [0.9.11] - 2026-09-14

### Added & Improved
- **Interactive Transposition Move Preview**: Clicking a candidate transposition in either the local or global transposition table immediately highlights the source and target squares on the chessboard, allowing users to visually evaluate alternate paths before adding them.
- **Smart Move Highlight Auto-Clear**: Transposition move highlights automatically clear when navigating to different board positions, switching tabs away from Transpositions, or activating another move.
- **Active Course Auto-Selection in Settings**: The Unified Settings dialog now automatically detects and selects the currently open repertoire upon opening or switching courses, keeping course configuration perfectly synchronized with Creator view.
- **Real-Time Maintenance Coverage Feedback**: Maintenance dialog displays actual Lichess coverage percentages with an immediate checkmark completion indicator once background enrichment tasks finish.
- **German & English Localization Polish**: Added localized tooltips and status strings for transposition preview interactions and maintenance task states.
- **Test Suite Expansion**: Added comprehensive automated tests for course auto-selection and transposition highlight clearing behaviors.

## [0.9.10] - 2026-09-13

### Added & Improved
- **Automated Stockfish Engine Downloader**: Integrated an automated engine downloader that fetches and extracts the latest official Stockfish release on-demand, reducing public installer size and maintaining clean separation.
- **Engine Setup & Configuration Dialog**: Added a dedicated dialog for downloading, selecting, and validating chess engines, with automatic thread and hash size recommendations.
- **Repertoire Mistake & Blunder Auditing**: Built an engine-driven audit pipeline (`audit_repertoire_mistakes` and `RepertoireMistakeScanThread`) to identify inaccuracies and blunders (centipawn loss > 50 cp) across all active repertoire moves.
- **Dedicated Lichess API Token Interface**: Added a modern dialog for configuring and validating Lichess API tokens, complete with one-click token generation links and permission guidance.
- **Multi-Threaded Maintenance Architecture**: Redesigned maintenance routines into parallel worker pipelines (engine analysis, Lichess synchronization, orphan cleanup, priority calculation) with responsive GUI progress reporting.
- **Creator & Hole Finder Enhancements**: Streamlined hole finding queries, optimized transposition tracking across unvisited positions, and polished board widget alignments.

## [0.9.9] - 2026-09-10

### Added & Improved
- **Smooth Piece Slide Animations with OutSine Easing**: Replaced linear interpolation with high-fidelity OutSine easing curves for natural deceleration and fluid piece motion.
- **Dynamic Square-Root Distance Scaling**: Implemented adaptive move animation durations based on Euclidean distance ($\text{scale} = 0.70 + 0.30 \cdot \sqrt{d / 2.0}$), scaling seamlessly between short 1-square pawn taps and long queen or rook slides.
- **VSync Refresh Rate Quantization**: Synchronized animation step durations directly to integer monitor refresh cycles (60Hz, 120Hz, 144Hz, 240Hz) to prevent sub-frame jitter and micro-stuttering.
- **Garbage Collection Suspension & Zero-Allocation Paint**: Suspended Python cyclic GC during active piece slides and pre-cached brushes/piece keys to eliminate 4-frame freezes and stutter.
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
