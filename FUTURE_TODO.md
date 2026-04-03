# Opening Fenix V2 - Future Features & Ideas

## 1. Multi-Language Support (English/German)
**Concept:**  
Make the application accessible to an international audience by supporting multiple languages (starting with English and German) for both the UI and the repertoire content.

**Implementation Ideas:**
* **UI Translation:** Use PyQt's built-in `QTranslator` and `.ts`/`.qm` files to dynamically switch all buttons, labels, and menus between English and German.
* **Bilingual Comments:** The database schema for `Position` needs to be extended. Instead of a single `comment` column, we could have `comment_de` and `comment_en`.
* **Language Toggle:** A setting in the profile configuration that dictates which language is currently active. If a user switches to English, the UI updates, and the Candidate Moves table pulls from the `comment_en` column.

## ~~2. "Repertoire Overhaul" Mode (Position Checklist)~~ (BASIC IMPLEMENTATION V1 - 2026-03-30)
**Concept:**  
Introductes a guided "Review Mode" to track which variations have been checked.

**Current State:**
* **Tab Integrated**: "Rep. KONTROLLE" tab added to the Creator.
* **Basic Tracking**: Basic progress tracking implementation started.
* **Navigation**: Basic "Next Unseen" logic in place.

**Next Steps (V2):**
* **Visual Cues**: Add checkmarks (✅) in the tree view for fully reviewed branches.
* **Session Persistence**: Ensure review state is saved across application restarts.

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

## ~~6. Performance Optimization & AI Compatibility~~ (COMPLETED)
**Concept:**  
Revisit the codebase to ensure it runs smoothly and is structured in a way that is easily understandable for AI agents and future developers.

*(Update: This was completed via the massive V2 architecture overhaul. Monoliths were broken into `core/services/` and `core/db/`, and PEP-484 typing/docstrings were added.)*
* **Performance Audit:** Identify and fix bottlenecks in the UI rendering and database access.
* **Refactoring for AI:** Improve code readability, add comprehensive docstrings, and ensure modularity to help AI agents (like Junie) understand and modify the project more effectively.
* **Code Consistency:** Ensure all modules follow the same architectural patterns and naming conventions.

## ~~7. Repertoire Hole Finder (Lichess Data Integration)~~ (BASIC IMPLEMENTATION V1 - 2026-03-30)
**Concept:**  
Identify "holes" in the repertoire—moves or positions not covered based on Lichess popularity.

**Current State:**
* **Tab Integrated**: "Rep. Loch Finder" tab added to the Creator.
* **Lichess Query**: Integrated backend logic to fetch common moves and probabilities.
* **Basic UI**: Results table with "Jump to position" functionality implemented.

**Next Steps (V2):**
* **Priority Matching**: Filter results by potential priority score impact.
* **Bulk Enrichment**: Add a feature to "Cover all high-priority holes" in a single batch.

## 9. User Documentation & Guides
**Concept:**  
Create comprehensive documentation to help both new and experienced users get the most out of Opening Fenix V2.

**Implementation Ideas:**
* **Quick Start Guide:** A concise "How-To" document (e.g., `QUICKSTART.md`) covering profile creation, repertoire importing, and starting your first training session.
* **Deep Dive Technical Guide:** A detailed manual explaining the application's core logic:
  * **Priority Scores:** How the "Potential Score" vs "Realized Score" is calculated based on Lichess data.
  * **Level Inheritance:** The rules governing how move importance (Levels 1-N) propagates through branches and transpositions.
  * **ELO Categories:** How the application selects relevant data based on the user's targeted ELO.
  * **Move Processing:** What happens under the hood when a new move is added or a PGN is imported.

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

## 14. Full Course Export
**Concept:**  
Create a comprehensive "Course Export" feature that generates a structured folder containing everything needed to share or backup a complete opening course.

**Export Package Contents:**
* **README.md:** Automatically generated file containing the course description and technical instructions on how to import the course into Opening Fenix (e.g., target directories).
* **Repertoire Database:** The actual `.db` file of the repertoire.
* **Level-Specific PGNs:** Separate PGN files for each level (Level 1, Level 2, etc.) with transpositions marked and no duplicates.
* **Instruction PGN:** A dedicated PGN file for verbal/textual instructions (Future Idea).
* **Typical Ideas PGN:** PGN files illustrating strategic themes and typical plans (Future Idea).
* **Model Games PGN:** A collection of high-level games illustrating the repertoire in practice (Future Idea).
* **Tactical Motifs PGN:** A PGN file focusing on common tactical patterns specific to the opening (Future Idea).

**Implementation Ideas:**
* **Export Wizard:** A UI dialog to select which components (DB, PGNs, Ideas, Games) to include in the export.
* **Folder Structure:** Clean organization (e.g., `/PGN/Levels/`, `/Games/`, `/Tactics/`).
* **Zip Export:** Create a `.zip` archive of the entire repertoire folder for easy sharing.

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