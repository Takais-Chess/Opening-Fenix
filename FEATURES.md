# Opening Fenix V2 - Project Features

Opening Fenix V2 is a chess repertoire management and training application. It allows users to build, analyze, and train their chess openings using local databases, stockfish engine analysis, and Lichess explorer data.

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
*(Brief overview based on file context, assumes presence of standard training features)*
*   **Spaced Repetition / Flashcards:** Train the repertoire positions against the computer.
*   **Profile Management:** Supports different user profiles to track individual progress.
