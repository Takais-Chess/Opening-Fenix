# Opening Fenix V2 - Project Features

Opening Fenix V2 is a chess repertoire management and training application. It allows users to build, analyze, and train their chess openings using local databases, stockfish engine analysis, and Lichess explorer data. The application features a premium Glassmorphism UI with full 4K support and smooth animations.

## 1. User Interface & Aesthetics
*   **Glassmorphism Design:** A modern, premium aesthetic with semi-transparent backgrounds, vibrant gradients, and sleek dark modes.
*   **Resolution-Relative Scaling:** Fully responsive UI designed for High-DPI and 4K monitors. All fonts, buttons, and layouts scale proportionally to the screen resolution.
*   **Premium Animations:** Native Qt-based piece movement animations featuring cubic easing for a natural feel, including piece "lifting" and shadow effects during moves.

## 1. Repertoire Creator (Creator Window)
The core module for building and editing opening repertoires.

### Board & Navigation
*   **Interactive Chess Board:** Visual representation of the position using SVG pieces. Supports making moves via drag-and-drop or clicking.
*   **Navigation Controls:** Buttons to go to the start position, go back one move, or go forward (following the highest priority move).
*   **Keyboard Navigation:** Use Left/Right arrow keys to navigate the move tree.
*   **Explorer Arrows:** Visual arrows on the board highlighting candidate moves from the repertoire. Green arrows indicate Level 1 (core) moves, light green indicates deeper levels.

### Candidate Moves Tree
*   **Move List:** Displays all known moves from the current position.
*   **Move Information:** Shows the move notation (SAN), Priority Score (likelihood of occurring), comments, and repertoire Level.
*   **Context Menu:** Right-click moves to delete them, assign NAGs (Novelty Annotation Glyphs like "!", "?", "!?"), or change the move's repertoire Level.

### Details & Annotation
*   **Comments:** Add text comments to any position.
*   **Variation Names:** Assign up to 3 hierarchical variation names to a position (e.g., "Sicilian Defense" -> "Najdorf" -> "Poisoned Pawn").
*   **Evaluation Symbols:** Quick-insert buttons for standard chess evaluation symbols (e.g., "+-", "=", "-+").

### Engine Analysis
*   **Local Engine Support:** Configure a UCI engine (like Stockfish) for local analysis.
*   **Live Analysis:** Toggle engine analysis on/off for the current position.
*   **Configuration:** Adjust analysis depth, thread count, and the number of multi-PV lines.
*   **Live Output Table:** Displays the engine's evaluation score, depth, and calculated principal variation (PV).
*   **Bulk Database Analysis:** Batch analyze all positions in the repertoire up to a specific depth to find "Good Moves" automatically.

### Lichess Integration (Common Moves)
*   **Live Explorer Data:** View the top 10 most common moves played in the current position based on Lichess data.
*   **Data Metrics:** Shows White Win %, Draw %, Black Win %, and Total games played.
*   **Database Selection:** Choose between "Low" (<1400), "Mid" (1400-2000), "High" (>2000), or "Masters" databases.
*   **Bulk Import:** Fetch and save Lichess data for all opponent positions in the repertoire to enable priority/probability calculations.
*   **Quick Add:** Double-click a move in the Common Moves table to instantly play it and add it to the repertoire.

### Import & Export
*   **PGN Import:** Import games or variations via PGN text pasting or from a `.pgn` file. Moves can be assigned to a specific repertoire Level during import.
*   **PGN Export:** Export the entire repertoire, or a specific branch starting from the current position, to a `.pgn` file. Supports exporting up to a maximum repertoire level.
*   **Database Export:** Backup the raw SQLite `.db` repertoire file.

### Repertoire Settings & Management
*   **Directory-Based Storage (New in V2.1):** Repertoires are now organized into dedicated subfolders, making it easier to manage associated files and exports.
*   **Automatic Asset Initialization:** New repertoires are automatically provisioned with standard assets:
    - **Model Games.pgn:** For collecting instructive games.
    - **Typical Motives.pgn:** For documenting strategic patterns.
    - **Tactics/Tactics.pgn:** For opening-specific tactical puzzles.
*   **Metadata:** View repertoire stats (number of moves, analysis depth, associated ELO).
*   **Levels Management:** Add, rename, and organize Repertoire Levels (e.g., "Core", "Sidelines", "Tricks").
*   **Themes:** Change the visual theme of the chess board (e.g., "Blau (Turnier)").
*   **Audio:** Toggle and adjust volume for move and capture sound effects.
*   **Priority Calculation:** Automatically calculate the mathematical probability (Priority Score) of reaching any position based on the imported Lichess frequency data.

## 2. Core Architecture

*   **Database (SQLAlchemy):** Uses SQLite to store positions, moves, repertoire structures, Lichess cache, and metadata.
*   **Multithreading (PyQt6 QThread):** Engine analysis, Lichess data fetching, and Island detection are handled on background threads to keep the UI responsive.
*   **Probability Flow:** Complex algorithm to cascade move probabilities down the repertoire tree, handling both user turns (repertoire choices) and opponent turns (statistical likelihood).

## 3. Training Module (Main Window)
The main module for practicing and mastering opening repertoires.

*   **Spaced Repetition System (SRS):** Advanced training logic that schedules move reviews based on mastery levels (Level 0 to 5), ensuring efficient memory retention.
*   **Adaptive Training:** Automatically presents moves that are "due" for training, while allowing manual selection of specific repertoires.
*   **"Freies Training" (Free Training):** A stateless profile for immediate, progress-free practice. It uses an in-memory database to allow training without persisting progress to disk.
*   **Course Introduction & Onboarding:** A beautiful, responsive splash screen that welcomes users to a new repertoire before they start learning their first moves, pulling metadata from the Creator.
*   **Profile Management:** Comprehensive profile system to track individual training progress, mastery levels, and SRS schedules across multiple repertoires.
*   **Real-time Feedback:** Visual indicators for correct/incorrect moves and immediate repertoire tree navigation during practice.
*   **Smart Variation Filtering:** Dropdown menu to filter training by specific variations. Selecting a parent variation automatically includes all its sub-variations to ensure comprehensive practice.
*   **Quick Tools:** Integrated toolbar for instant access to the Creator, Lichess Analysis, and Autoplay toggles directly from the training position.
