# Opening Fenix V2

Opening Fenix V2 is a powerful chess repertoire management and training application. It allows users to build, analyze, and train their openings using local engine analysis, statistical Lichess data, and a custom Spaced Repetition System (SRS).

## Features

- **Premium Glassmorphism UI**: Modern, high-contrast interface with native Qt animations for smooth piece movement and interactions.
- **High-DPI & 4K Support**: Fully responsive design with resolution-relative scaling for a sharp experience on any monitor.
- **Robust Repertoire Creator**: Interactive chess board with move validation, hierarchical variation naming, and automated name propagation. Includes a **Lichess Analysis Shortcut** to instantly open the current position on lichess.org.
- **Engine Integration**: Live position evaluation using UCI engines (e.g., Stockfish). Bulk analysis tools to automatically evaluate entire databases.
- **Lichess Data Integration**: Statistical win rates and move frequencies across multiple ELO categories.
- **Spaced Repetition Training**: Advanced SRS training schedules based on mastery levels. Includes a stateless **"Freies Training"** (Free Training) profile for immediate, progress-free practice.
- **Course Introduction Onboarding**: A welcoming splash screen that introduces new repertoires to the user before they start learning.
- **Secure Input Handling**: Comprehensive validation for PGN imports and database operations to ensure repertoire integrity.
- **Flexible Import/Export**: Import from PGN files or export your repertoire (entirely or specific branches) for use in other software.
- **Profile Management**: Support for multiple user profiles to track individual progress and settings.

## Requirements

- **Python**: 3.14+
- **Platform**: Windows (primary support for executable builds)
- **Dependencies**: PyQt6, SQLAlchemy, python-chess, pytest

## Setup & Installation

1. **Clone the repository**:
   ```powershell
   git clone https://github.com/felixbrunner12-lab/Opening-Fenix.git
   cd Opening-Fenix
   ```

2. **Set up a Virtual Environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Install Chess Engine**:
   - Place your chess engine executable (e.g., `stockfish.exe`) in the `engines/` directory.
   - The application looks for `stockfish*.exe` by default, but you can configure the exact path in `config.json`.

## Documentation

For a detailed guide on how to use the application and its underlying logic, refer to:
- [**Quick Start Guide**](QUICKSTART.md): Learn how to set up profiles, import repertoires, and start training.
- [**Technical Deep Dive**](TECHNICAL_DEEP_DIVE.md): Understand the mathematics behind priority scores, level reachability, and architecture internals.

## Usage

### Running from Source
To start the application during development:
```powershell
.\.venv\Scripts\python.exe main.py
```
Upon startup, the application presents a **Login Dialog**. From there, you can choose a profile to enter the **Trainer (Main Window)** or open the **Repertoire Creator**.

### Configuration
The global configuration is stored in `config.json`. Key settings include:
- `engine_path`: Full path to the UCI engine executable.
- `lichess_token`: (Optional) Your Lichess API token for higher rate limits.
- `theme`: The visual board theme (e.g., "Blau (Turnier)").
- `last_profile`: The last active user profile.

The application automatically searches for a `stockfish*.exe` file within the `engines/` directory if no `engine_path` is configured.

## Scripts & Development Tools

### Building the Executable
Use the provided batch script to create a standalone Windows application:
```powershell
.\build_executable.bat
```
The output will be generated in `dist\Opening Fenix`.

## Testing & Coverage

Tests are managed via `pytest` with `pytest-cov` for coverage analysis. The suite includes robust cleanup logic for Windows and covers critical UI and backend services.

### Running Tests
```powershell
# Run all tests
.\.venv\Scripts\python.exe -m pytest

# Run tests with coverage report
.\.venv\Scripts\python.exe -m pytest --cov=opening_fenix
```

### Current Status
- **Overall Coverage**: ~65%
- **Critical Modules**:
  - `MainWindow`: 78%
  - `BoardWidget`: 69%
  - `CreatorWindow`: 43%
- **Total Tests**: 147 passing

## Project Structure

- `main.py`: The main entry point of the application.
- `opening_fenix/`: Source code directory.
  - `core/`: Application backend logic.
    - `services/`: Modular services for training (SRS), Lichess API integration, engine analysis, and repertoire tree logic.
    - `db/`: Database management, connection pooling, and SQLAlchemy models.
  - `gui/`: Main training interface and UI components (Glassmorphism, Scaling).
  - `creator/`: UI for the repertoire editing and management tool.
- `assets/`: Icons, Logos, Piece Sets (SVG/PNG), and Sounds.
- `engines/`: Folder for UCI chess engine executables (e.g., Stockfish).
- `profiles/`: User-specific profiles and SRS training data (`.db` files).
- `repertoires/`: Stores opening repertoires. Each repertoire has its own subfolder containing the SQLite `.db` database and its associated assets (`.pgn` files, specialized folders).
- `tests/`: Automated test suite with unit and integration tests.
- `Opening Fenix.spec`: PyInstaller configuration for building the application.

## License

TODO: Add license information.

## Future Work

See [FUTURE_TODO.md](FUTURE_TODO.md) for planned features:
- Multi-language support (English/German).
- Repertoire Overhaul Mode (Position Checklist).
- Tactics and Endgame Trainer.
- Dynamic Rating System (Opening Elo).
