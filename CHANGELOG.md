# Changelog

All notable changes to this project will be documented in this file.

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
