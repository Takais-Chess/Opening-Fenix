# Opening Fenix V2 - Future Features & Ideas

## 1. Multi-Language Support (English/German) (IN PROGRESS)
**Concept:**  
Make the application accessible to an international audience by supporting multiple languages (starting with English and German) for both the UI and the repertoire content.

**Implementation Progress:**
* **Multilingual Notation:** Successfully implemented English/German chess notation (`Nf3` vs `Sf3`) throughout the UI and backend. 
* **UI Translation (Future):** Full dynamic UI translation using `QTranslator` is planned for a future release to localize all menus and dialogs.

## 4. Tactic & Endgame Trainer (Prebuilt Scenarios)
**Concept:**  
A separate module independent of the opening repertoires, focused on solving specific puzzles or playing out prebuilt variations (e.g., "Mate in 3", "Lucena Position", "Philidor Position").

**Implementation Ideas:**
* **Scenario Database:** A separate `.db` file (e.g., `tactics.db`) that stores isolated FENs, the winning move sequence, and explanatory text for each step.
* **Trainer Mode:** A new main menu option. It presents the user with a puzzle. If they make the right move, it plays the opponent's response. If they make a wrong move, it shows a hint or the explanatory text.
  * **Categorization:** Tags for puzzles (Pins, Forks, Endgames) to allow focused training sessions.

## ~~5. Design Refinement & Visual Enhancements~~ (COMPLETED)
**Concept:**  
Improve the overall look and feel of the application to make it more professional and user-friendly.

**Implementation Ideas:**
* **UI Overhaul:** Implemented premium glassmorphism designs for the Login and Creator windows.
* **Layout Optimization:** Refined the profile selection grid and aligned UI panels for better visual balance.

## ~~6. Performance Optimization & AI Compatibility~~ (COMPLETED - 2026-04-14)
**Concept:**  
Revisit the codebase to ensure it runs smoothly and is structured in a way that is easily understandable for AI agents and future developers.

*(Update: This was completed via the massive V2 architecture overhaul and a follow-up systematic performance audit.)*
* **Performance Audit:** Conducted a segmented audit of database interactions, UI rendering, and engine communication to resolve bottlenecks.
* **Refactoring for AI:** Improved code readability, added comprehensive docstrings, and ensured modularity to help AI agents understand and modify the project more effectively.
* **Code Consistency:** All modules now follow consistent architectural patterns and naming conventions.


## ~~9. User Documentation & Guides~~ (COMPLETED - 2026-04-06)
**Concept:**  
Create comprehensive documentation to help both new and experienced users get the most out of Opening Fenix V2.

**Achievements:**
* **Quick Start Guide:** Created `QUICKSTART.md` covering the essentials.
* **Technical Deep Dive:** Created `TECHNICAL_DEEP_DIVE.md` explaining probabilities, levels, and SRS logic.
* **Onboarding Guided Tour:** Implemented an interactive in-app tour for new profiles to ensure a seamless first-time experience.

## ~~8. Robustness & Testing Suite~~ (COMPLETED - 2026-03-29)
**Concept:**  
Build a rock-solid foundation for the application by ensuring all core services are heavily tested.

**Achievements:**
* **Overall Coverage**: Reached **65%** milestone with 147 passing tests.
* **Core Stability**: Reached **78%** on `MainWindow` and **69%** on `BoardWidget`.
* **UI Lifecycle**: Automated verification of all window transitions (Trainer, Creator, Settings).
* **Input Validation**: Hardened PGN imports and database migrations against malformed data.
* **Windows Cleanup**: Solved persistent file-lock issues during automated testing.

## ~~10. Lichess API Token Interface~~ (COMPLETED - 2026-04-02)
**Concept:**
Provide a user-friendly way to input and manage the Lichess API token within the application, rather than requiring manual editing of `config.json`.

**Implementation Details:**
* **Settings Integration:** Added a dedicated section in the Creator Repertoire Settings for token management.
* **Token Validation:** Implemented a "Verbindung testen" button that verifies the token against the Lichess API and displays the account username.
* **Visibility Control:** Added a show/hide toggle for the token field to protect user privacy.
* **Automatic Config Sync:** The application now automatically saves and loads the token from `config.json` without manual intervention.
* **Analysis Shortcut:** Integrated a "Microscope" Lichess button to instantly open the current board position in the browser.

## 11. CI/CD Integration & High Coverage (80%+)
**Concept:**  
Automate testing on every push and reach the elusive 80% coverage target, especially for the complex `CreatorWindow`.

**Implementation Ideas:**
* **GitHub Actions**: Set up a pipeline to run `pytest` on Windows runners for every Pull Request.
* **Creator Deep Dive**: Add granular tests for the Creator's specific sub-tabs (Analysis, Kontrolle) and its internal state-machine.
* **Screenshot Comparison**: Implement visual regression tests for the board and glassmorphism UI.

## ~~12. Dynamic Rating System (Opening Elo)~~ (COMPLETED - 2026-03-30)
**Concept:**  
Assign a "Strength" score to the user's mastery of specific opening lines.

**Achievements:**
* **Elo Tracking**: Integrated into the `MainWindow` and `TrainingManager`.
* **Level Mapping**: Tied mastery levels to target Elo ranges (e.g., Level 1 = 1500 Elo).
* **Live Display**: User's estimated Opening Elo is displayed and updated in real-time during training.

## ~~13. Prioritätsbasierte Level-Herabstufung~~ (COMPLETED)
**Konzept:**
Eine Funktion in den Repertoire-Einstellungen des Creators, mit der man Züge basierend auf ihrer Priorität (Häufigkeit) herabstufen oder umkategorisieren kann.

**Umsetzungsideen:**
* **Massenbearbeitung:** Ein Tool in den Einstellungen, das z.B. alle Züge mit einer Priorität > 1% automatisch auf Level 1 (oder ein anderes wählbares Level) setzt.
* **Batch-Reorganisation:** Ermöglicht die schnelle Strukturierung eines großen Repertoires, indem wichtige (häufige) Züge priorisiert werden.
* **Sicherheitsabfrage:** Anzeige der Anzahl der betroffenen Züge vor der Durchführung der Änderung.


## 16. Custom Repertoire Cover Images
**Concept:**
Since repertoires now live in dedicated subfolders, allow users to place a `cover.png` or `cover.jpg` inside the folder.
The `RepertoireSelectionDialog` and Main Window can display these images in a visual grid instead of plain buttons, making the app feel much more premium and personalized.

## ~~15. Course Introduction & First-Time User Experience~~ (COMPLETED - 2026-04-02)
**Concept:**  
Provide a welcoming and informative experience when a user opens a course or repertoire for the first time (i.e., no moves have been learned yet).

**Implementation Details:**
* **Welcome Window:** A special splash screen or modal that triggers automatically if the "learned moves" count for the current repertoire is zero.
* **Course Introduction:** Display high-level information about the course, its goals, and key strategic themes based on the description entered in the Creator settings.
* **"Start Learning" Button:** A clear call-to-action to lead the user directly into their first lesson without additional clicks.
* **First-Time Trigger:** Backend logic dynamically checks the repertoire's state to conditionally display the splash window, ensuring it doesn't interrupt daily training.

## ~~17. Repertoire Storage Reorganization~~ (COMPLETED - 2026-04-03)
**Concept:**  
Transition from a flat `.db` structure to dedicated repertoire subfolders to allow for better organization and multi-file asset management.

**Achievements:**
* **Folder Hierarchy:** Each repertoire now resides in `repertoires/{name}/`.
* **Asset Provisioning:** Automatic creation of `Model Games.pgn`, `Typical Motives.pgn`, and `Tactics/` on initialization.
* **Migration Script:** Integrated logic to transparently upgrade existing databases to the new structure.

## 18. Create Example Repertoire(s)
**Concept:**
Provide users with one or two high-quality example repertoires (e.g., "The Italian Game - Core Variations") to showcase how to use the Creator, and to provide immediate training content for new users.


## 20. Repertoire Game Analysis (Lichess Integration)
**Concept:**  
Analyze a player's real games on Lichess to identify when they deviate from their defined opening repertoire. This helps in pinpointing "holes" in their knowledge based on actual performance.

**Implementation Ideas:**
* **Game Fetching:** Integrate Lichess API to download games for a specific username, filtered by time period (date range) and time control (Blitz, Rapid, Classical).
* **Automated Comparison:** The system iterates through the game's PGN and compares each position against the active repertoire database.
* **Deviation Detection:** Identify the exact move where the game "left the opening" (i.e., the first move not recorded in the repertoire).
* **Categorization:** Distinguish between "intentional deviations" (new lines to learn) and "mistakes" (lines that were in the repertoire but forgotten).
* **Visual Feedback**: Show a summary report for each game: "Deviated at move 12 (Repertoire coverage: 85%)".

## 21. Repertoire Schema Versioning
**Concept:**
The current migration system uses `PRAGMA table_info` checks. Implementing a dedicated `SchemaVersion` table would allow for more robust migrations and better tracking of data structure evolution.

## 22. Database Cleanup & Optimization
**Concept:**
Remove dead columns such as `Position.good_moves`, `Position.popularity`, and `Position.popularity_elo` identified during the version 2.4.0 audit.
Implement a custom `DatabaseCorruptionError` to handle malformed files more gracefully than a generic `sqlite3.DatabaseError`.