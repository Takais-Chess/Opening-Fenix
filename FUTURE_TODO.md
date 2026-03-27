# Opening Fenix V2 - Future Features & Ideas

## 1. Multi-Language Support (English/German)
**Concept:**  
Make the application accessible to an international audience by supporting multiple languages (starting with English and German) for both the UI and the repertoire content.

**Implementation Ideas:**
* **UI Translation:** Use PyQt's built-in `QTranslator` and `.ts`/`.qm` files to dynamically switch all buttons, labels, and menus between English and German.
* **Bilingual Comments:** The database schema for `Position` needs to be extended. Instead of a single `comment` column, we could have `comment_de` and `comment_en`.
* **Language Toggle:** A setting in the profile configuration that dictates which language is currently active. If a user switches to English, the UI updates, and the Candidate Moves table pulls from the `comment_en` column.

## 2. "Repertoire Overhaul" Mode (Position Checklist)
**Concept:**  
When users want to completely review and update an old repertoire, it is impossible to manually keep track of which variations and transpositions have already been checked. This feature introduces a guided "Review Mode".
To start this mode it should be somewhere in the settings

**Implementation Ideas:**
* **Tracking Table:** A new temporary table or state file that stores `(fen, reviewed_boolean)` for the current session.
* **Floating Widget/Panel:** A small, non-intrusive floating window that only appears if this mode is active, that displays the progress (e.g., "Positions Reviewed: 45 / 320").
* **Navigation Buttons:** 
  * "Mark as Reviewed" (automatically moves to the next position).
  * "Go to Next Unseen" (jumps the board to the unseen position with the lowest depth/move number, ensuring a top-down review).
  * "Reset Progress".
* **Visual Cues:** In the Creator, moves leading to already reviewed positions could have a small checkmark (✅) next to them in the tree but only if also all descendants have already been seen.
* this should only reset 

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

## 7. Repertoire Hole Finder (Lichess Data Integration)
**Concept:**  
A way to identify "holes" in the repertoire—moves or positions that are not currently covered but should be based on their popularity and success in online play (Lichess).

**Implementation Ideas:**
* **Priority-Based Discovery:** Search for moves in the Lichess database that are not in the current repertoire but would have a "Potential Priority Score" of >1 if they were included.
* **Coverage Analysis:** Compare the current repertoire tree against a configurable "depth" or "mastery" level from the Lichess Cloud Eval or opening explorer.
* **Direct Integration:** A button in the Creator or a separate "Audit" tool that lists these missing moves and allows the user to quickly add them with a single click.

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

## ~~8. Robustness & Testing Suite~~ (COMPLETED)
**Concept:**  
Build a rock-solid foundation for the application by ensuring all core services are heavily tested against edge cases and malformed inputs.

**Implementation Details:**
* **Robust Cleanup:** Implemented resilient temporary directory management in `conftest.py` to handle Windows-specific file locks.
* **Input Validation:** Added comprehensive validation for PGN imports, priority calculations, and engine analysis.
* **Move Integrity:** Enforced legal move checks in the `CreatorBackend` to prevent database corruption.

## 10. Lichess API Token Interface
**Concept:**
Provide a user-friendly way to input and manage the Lichess API token within the application, rather than requiring manual editing of `config.json`.

**Implementation Ideas:**
* **Settings Dialog:** A new tab in the settings window where the user can paste their token.
* **Token Validation:** A "Test Connection" button that verifies the token by making a simple request to the Lichess API.
* **Startup Check:** If the application starts and no token is found in `config.json`, prompt the user with a setup wizard to provide one.