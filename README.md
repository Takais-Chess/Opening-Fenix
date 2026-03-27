# Opening Fenix V2

Opening Fenix V2 is a powerful chess repertoire management and training application. It allows users to build, analyze, and train their openings using local engine analysis, statistical Lichess data, and a custom Spaced Repetition System (SRS).

## Features

- **Premium Glassmorphism UI**: Modern, high-contrast interface for both the Login and Repertoire Creator windows.
- **Robust Repertoire Creator**: Interactive chess board with move validation, hierarchical variation naming, and automated name propagation.
- **Engine Integration**: Live position evaluation using UCI engines (e.g., Stockfish). Bulk analysis tools to automatically evaluate entire databases.
- **Lichess Data Integration**: Statistical win rates and move frequencies across multiple ELO categories.
- **Spaced Repetition Training**: Advanced SRS training schedules based on mastery levels.
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

## Testing

Tests are managed via `pytest`. The suite includes robust cleanup logic for Windows and comprehensive input validation tests.

```powershell
# Run all tests using the project's virtual environment
.\.venv\Scripts\python.exe -m pytest

# Run specific test suites
.\.venv\Scripts\python.exe -m pytest tests/test_input_validation.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_inheritance.py -v
```

## Project Structure

- `main.py`: The main entry point of the application.
- `opening_fenix/`: Source code directory.
  - `core/`: Application backend logic.
    - `services/`: Modular services for training (SRS), Lichess API integration, engine analysis, and repertoire tree logic.
    - `db/`: Database management, connection pooling, and SQLAlchemy models.
  - `gui/`: Main training interface and UI components.
  - `creator/`: UI for the repertoire editing and management tool.
- `assets/`: Icons, Logos, Piece Sets, and Sounds.
- `engines/`: Folder for UCI chess engine executables.
- `profiles/`: User-specific profiles and SRS training data (`.db` files).
- `repertoires/`: Stores opening repertoires as SQLite databases.
- `tests/`: Automated test suite.
- `Opening Fenix.spec`: PyInstaller configuration for building the app.

## License

TODO: Add license information.

## Future Work

See [FUTURE_TODO.md](FUTURE_TODO.md) for planned features:
- Multi-language support (English/German).
- Repertoire Overhaul Mode (Position Checklist).
- Tactics and Endgame Trainer.
- Dynamic Rating System (Opening Elo).
