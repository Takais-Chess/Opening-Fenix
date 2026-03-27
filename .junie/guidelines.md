# Development Guidelines for Opening Fenix

## 1. Build and Configuration Instructions

### Prerequisites
- Python 3.x (tested with Python 3.14+)
- Recommended: Use a virtual environment (`.venv`)

### Installation
```powershell
pip install -r requirements.txt
```

### Configuration
- `config.json`: Stores global settings such as `last_profile`, `engine_path`, and `lichess_delay`. This file is located in the project root during development.
- `engines/`: Place chess engine executables (e.g., Stockfish) here. The app automatically searches for "stockfish*.exe" as a default.

### Building the Executable
To create a standalone Windows executable:
1. Ensure `pyinstaller` is installed.
2. Run `build_executable.bat`.
3. The output will be in `dist\Opening Fenix`.

---

## 2. Testing Information

### Running Tests
Tests use `pytest`. You must ensure the project root is in `PYTHONPATH`.

```powershell
# Run all tests
$env:PYTHONPATH="."; .\.venv\Scripts\python.exe -m pytest

# Run a specific test with verbose output
$env:PYTHONPATH="."; .\.venv\Scripts\python.exe -m pytest tests\test_repertoire.py -v
```

### Adding New Tests
- Place tests in the `tests/` directory with the prefix `test_`.
- **Fixtures**: Use the fixtures defined in `tests/conftest.py` to isolate tests from production data:
  - `mock_user_dir`: Redirects all user data paths to a temporary directory.
  - `sample_repertoire`: Sets up a minimal repertoire for testing.
  - `repertoire_manager`: Provides a pre-configured `RepertoireManager`.

### Simple Test Example
Below is a demonstration of how to write a test using existing fixtures.

```python
import os
import pytest
import opening_fenix.core.data_tools

def test_mock_user_dir(mock_user_dir):
    """Verifies that the user directory is correctly mocked."""
    user_dir = opening_fenix.core.data_tools.get_user_dir()
    assert user_dir == mock_user_dir
    assert os.path.exists(os.path.join(user_dir, "profiles"))
    assert os.path.exists(os.path.join(user_dir, "repertoires"))

def test_sample_repertoire_exists(mock_user_dir, sample_repertoire):
    """Verifies that the sample repertoire is created in the mock user directory."""
    repo_path = os.path.join(mock_user_dir, "repertoires", f"{sample_repertoire}.db")
    assert os.path.exists(repo_path)
```

---

## 3. Additional Development Information

### Database Schema
- Managed via **SQLAlchemy** in `opening_fenix/core/models.py`.
- **Repertoire DB**: Stores positions, moves, levels, and Lichess metadata.
- **User Profile DB**: Stores SRS training data (`box`, `next_due`, `streak`) and user-specific repertoire settings.

### Variation Inheritance
The project uses a custom inheritance mechanism for position variations:
- If a position does not have a `variation_1` name, it inherits it from its parent in the move tree (following the highest priority move).
- This is implemented in `RepertoireManager._find_inherited_v1`.
- Cached values (`cached_v1`, etc.) in the `positions` table are used to optimize performance.

### GUI Framework
- Built with **PyQt6**.
- The main application logic resides in `opening_fenix/gui/main_window.py`.
- The `CreatorWindow` (`opening_fenix/creator/creator_window.py`) is used for managing repertoires outside the main training loop.

### Code Style
- Follow standard PEP 8 guidelines.
- Use `logging` or `print` for debugging (errors are caught and shown via `QMessageBox` in `main.py`).
- SQLite `WAL` mode is used for better performance and concurrency; ensure connections are closed properly to avoid file locks.
