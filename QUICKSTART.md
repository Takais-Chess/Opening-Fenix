# Quick Start Guide - Opening Fenix V2

Welcome to Opening Fenix V2! This guide will help you get started with building and training your opening repertoire.

## 1. Create a Profile
When you first launch the application, you'll need to create or select a **Profile**. 
- Profiles store your individual training progress and settings.
- Click **"Neues Profil"** to create a new one.
- **Guided Tour**: New profiles will automatically be offered an interactive **Guided Tour** to walk them through the interface and core features.

## 2. Create or Select a Repertoire
Once inside, you'll see a list of repertoires.
- **New Repertoire**: Click **"Neues Repertoire"** to create a blank slate. New repertoires are automatically initialized with three default levels: **1. Grundlagen**, **2. Tiefe Theorie**, and **3. Nachschlagewerk**.
- **Settings**: Use the **"Einstellungen"** button to set your target Lichess API Token, ELO range, and repertoire color (Black/White).

## 3. Importing Moves
There are two main ways to add moves to your repertoire:
1.  **Manual Entry**: Use the **Repertoire Creator** window. Play moves on the board; if it's your turn, they are added to the repertoire.
2.  **PGN Import**: In the Creator settings, use the **"PGN Importieren"** button to bulk-import a file. The system automatically repairs move sequences and ensures repertoire integrity after the import.

## 4. Identifying "Holes"
Switch to the **"Rep. Loch Finder"** (Hole Finder) tab in the Creator.
- Click **"Lücken suchen"** to see which common moves (based on Lichess data) you haven't covered yet.
- **Priority Sorting**: Results are automatically sorted by frequency, helping you focus on the most common lines first.
- **Transposition Awareness**: The finder correctly identifies transpositions and respects your minimum reached level for each position to avoid false positives.
- Double-click a row to jump to that position on the board.

## 5. Training
Go back to the Main Window and click **"Training starten"**.
- **Onboarding Experience:** New users are guided by a premium tour and an optional FAQ sequence before starting their first training session.
- **Course Introduction:** When opening a new repertoire with zero learned moves, you will be greeted by a splash screen showing the course description and stats. Click **"JETZT LERNEN"** to dive right in.
- **New Mode**: Learn moves you haven't seen yet.
- **Due Mode**: Review moves using the **Spaced Repetition** system.
- **Filters**: Use the dropdown to focus on a specific variation (e.g., "Sicilian Defense").

## 6. Lichess Integration
For the best experience, add your **Lichess API Token** in the Repertoire Settings. This allows the application to fetch more accurate move probabilities and identify critical lines tailored to your ELO level.
You can also use the **Microscope Icon** in the Trainer or Creator to instantly analyze any position on Lichess.
