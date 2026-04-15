# Technical Deep Dive - Opening Fenix V2

This document explains the core technical logic and algorithms behind Opening Fenix V2.

## 1. Database Integrity & Recovery
Opening Fenix includes a robust system for handling SQLite database corruption (e.g., "malformed database" errors).

### Detection & Recovery
- **Validation**: On connection, the application performs an integrity check. If a database is found to be malformed, it triggers the recovery sequence.
- **Recovery Process**: 
    1. The corruption is logged, and the user is notified.
    2. A temporary recovery script is generated using the SQLite `.recover` command logic.
    3. Data is extracted into a new SQL dump and re-imported into a clean database file.
    4. The original malformed file is backed up before being replaced by the healthy recovered version.


## 2. Priority Scores (The BFS Probability Algorithm)
Opening Fenix uses a **Breadth-First Search (BFS)** traversal to calculate a **Priority Score** (Probability) for every move in the database.

### Initial State
The starting position (Root) is assigned a probability of **1.0**.

### Propagation Rules
1.  **User's Turn**: If multiple repertoire moves exist for the user, the probability is **split equally** among them.
2.  **Opponent's Turn**: The probability is distributed based on **Lichess Popularity Data**.
    - `Total Games = Sum(Lichess move counts) + Count(Rare moves not in Lichess)`
    - `Rare Move Weight`: Each move not found in Lichess data is treated as having **1 game** by default to ensure it still receives a small probability.
    - `Move Probability = Parent Probability * (Move Games / Total Games)`

### Purpose
This score represents how likely you are to encounter a specific position in a real game. It is used to:
- Sort candidate moves.
- Prioritize which moves you should learn first.

## 3. Level Reachability (Smart Repertoire Logic)
Repertoires are organized into **Levels** (1 to N).
- During training, you can set an **Active Level** (e.g., "Level 2").
- **Reachability Analysis**: A move is only presented if it is reachable from the root through a continuous path of moves that are **all within the active level limit**.
- **Transposition Awareness**: The system tracks the **Minimum Reached Level** for every unique position (FEN). If a position is reached via multiple paths, the "easiest" path (lowest level) determines its availability.
- This prevents the system from asking you about deep variations (Level 3) before you've learned the main lines (Level 1) that lead to them via transpositions.

## 4. ELO Categories
When fetching Lichess data, the application maps your chosen category to specific rating ranges:
- **Low**: 1600
- **Mid**: 1800, 2000
- **High**: 2200
- **Masters**: Uses the dedicated Lichess Masters Explorer (Elite-level games only).

## 5. Move Processing (PGN Import)
The PGN import service uses an optimized bulk-insert strategy:
- **Deduplication**: It uses an in-memory cache of FENs and UCIs to ensure that transpositions are correctly identified as the same position, preventing duplicate entries.
- **Automated Integrity Repair**: After bulk insertion, the system automatically runs a repair workflow that re-links orphaned moves and validates parent-child relationships across the entire repertoire.
- **Comment Merging**: Comments from PGN files are appended to positions. If a position appears in multiple lines with different comments, they are merged using a `|` separator.

## 6. Variation Inheritance
The variation structure (e.g., *Sicilian -> Najdorf*) is built dynamically.
- **Tag Inheritance**: If a position is tagged with a sub-variation (e.g., `variation_2 = "Najdorf"`) but is missing a top-level tag, it **recursively crawls up the tree** to find the nearest ancestor with a `variation_1` tag (e.g., "Sicilian").
- This ensures that filters in the Trainer remain consistent even if you only tag the "leaf" nodes of a variation.

## 7. Onboarding & Guided Tours
To enhance the First-Time User Experience (FTUE), the application implements a multi-stage onboarding system:
- **Guided Tour**: Uses a spotlight overlay mechanism to highlight key UI elements (Sidebar, Repertoire List, Training Controls) in sequence.
- **Contextual FAQs**: A series of pedagogical cards that explain the SRS methodology and how to use the "Loch Finder" effectively.
- **Conditional Triggering**: Onboarding states are persisted in the user profile to ensure they only trigger once, or can be reset manually from settings.

## 8. Lichess Elo Buckets Logic
The application fetches population-level move frequencies from Lichess. To ensure the most relevant data is used, it maps user settings to specific rating buckets:
- **Low (1600)**: Focuses on avoiding common blunders and learning solid fundamentals.
- **Mid (1800-2000)**: Incorporates more theoretical lines and common sidelines encountered in intermediate play.
- **High (2200)**: Prioritizes theoretically sound responses and engine-approved variations.
- **Masters**: Uses only the Lichess Masters database for elite-level theory.

---

## 9. Thread Management & UI Stability
To maintain a responsive "Glassmorphism" interface, Opening Fenix utilizes a strict background execution model for all CPU or I/O bound tasks.

### Worker Threads (`threads.py`)
- **AnalysisThread**: Wraps the Stockfish UCI bridge. It uses cooperative cancellation (`_is_canceled`) to ensure engine processes are killed before the GUI deletes the thread object.
- **HoleFinderThread**: Runs heavy BFS traversals. It is fully decoupled from the `CreatorWindow` to prevent UI freezing during large repertoire scans.
- **LichessLoaderThread**: Handles the asynchronous data fetching for the statistics dialogs.

### Lifecycle Protection
- **WindowManager Loop**: A centralized state machine (`opening_fenix/gui/window_manager.py`) manages the hand-off between the Login, Trainer, and Creator windows. 
- **Graceful Teardown**: `MainWindow` overrides `closeEvent` to ensure all SQLAlchemy sessions and background engines are flushed and terminated before the process exits, preventing persistent file locks on Windows.

## 10. Lichess API Backoff Controller
The Lichess integration features an intelligent "tempo" controller to comply with API rate limits:
- **Exponential Backoff**: If a `429 Too Many Requests` status is returned, the system immediately suspends operations for 60 seconds and increases the base delay logic (`delay * 1.5`).
- **Adaptive Recovery**: For every 50 successful requests, the system cautiously reduces the delay by 5%, allowing it to settle on the most optimal network throughput (minimum `0.05s`).

---

## 11. Development & Persistence

### Database Architecture
- **ORM**: Managed via **SQLAlchemy** in `opening_fenix/core/models.py`.
- **Persistence Layers**: 
  - **Repertoire DB**: Stores positions, moves, levels, and Lichess metadata.
  - **User Profile DB**: Stores SRS training data (`box`, `next_due`, `streak`) and user-specific repertoire settings.
- **Performance**: SQLite `WAL` (Write-Ahead Logging) mode is enabled for improved concurrency and performance.

### GUI Framework
- Built with **PyQt6**.
- Main application logic: `opening_fenix/gui/main_window.py`.
- Repertoire management: `opening_fenix/creator/creator_window.py`.

## 12. Testing Suite

### Running Tests
Tests use `pytest`. On Windows, ensure the project root is in `PYTHONPATH`:

```powershell
# Run all tests
$env:PYTHONPATH="."; .\.venv\Scripts\python.exe -m pytest
```

### Key Test Fixtures
Located in `tests/conftest.py`, these fixtures isolate tests from production data:
- `mock_user_dir`: Redirects all user data paths to a temporary directory.
- `sample_repertoire`: Sets up a minimal repertoire for testing.
- `repertoire_manager`: Provides a pre-configured `RepertoireManager`.

### Internal Utilities
- **Variation Inheritance**: Implemented in `RepertoireManager._find_inherited_v1`. It recursively crawls up the move tree to find the nearest ancestor with a `variation_1` tag.
- **Resolution Scaling**: Managed in `opening_fenix/gui/scaling.py` for High-DPI support.
