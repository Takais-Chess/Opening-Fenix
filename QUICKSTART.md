# 🚀 Quick Start Guide - Opening Fenix V2

Welcome to **Opening Fenix V2**! This guide will take you step-by-step from launching the application to building your first repertoire and mastering your opening moves with Spaced Repetition (SRS).

---

## 1. 👤 Profile Setup
When you launch Opening Fenix for the first time, you'll be prompted to select or create a **Profile**.
- **Profiles** store your individual training history, SRS review schedules, and settings.
- Click **"Neues Profil"** to create a profile with your name.
- **Guided Tour**: New profiles are automatically offered an interactive spotlight tour highlighting key interface controls.

---

## 2. 📚 Creating or Selecting a Repertoire
Once inside your profile dashboard, you will see your available opening repertoires.
- **Create a New Repertoire**: Click **"Neues Repertoire"** to start a new course (e.g., *"Sicilian Dragon for Black"*).
- **Default Repertoire Levels**: New repertoires automatically initialize with three structured levels:
  1. **1. Grundlagen** (Core main lines every player must know)
  2. **2. Tiefe Theorie** (Deeper tactical variations)
  3. **3. Nachschlagewerk** (Extended sidelines and rare moves)
- **Repertoire Settings**: Click **"Einstellungen"** to select your color (**White** or **Black**), target ELO range, and enter your Lichess API Token.

---

## 3. ♟️ Adding Moves & Importing PGNs
You can build your repertoire using two simple methods:

1. **Interactive Creator Window**:
   - Open the **Repertoire Creator**.
   - Make moves directly on the board. When playing moves for your chosen color, they are recorded as your repertoire candidate moves.
   - Add comments, assign variations (e.g. *"Najdorf Variation"*), or set level flags.
2. **Bulk PGN Import**:
   - In the Creator Settings, click **"PGN Importieren"**.
   - Select any PGN file from your computer (e.g., a chess book or course file).
   - Opening Fenix automatically imports the move tree, merges comments, deduplicates transpositions, and runs an integrity repair sequence.

---

## 4. 🔎 Finding "Holes" in Your Repertoire (Hole Finder 2.0)
Don't guess what your opponents will play—let Lichess data show you!
1. In the Creator, click the **"Rep. Loch Finder"** tab.
2. Click **"Lücken suchen"**.
3. Opening Fenix scans millions of real Lichess games at your ELO tier and compares them against your repertoire.
4. It lists opponent moves played frequently against you that you haven't prepared for yet, sorted by popularity.
5. **Double-click any hole** in the table to jump directly to that position on the board and add your response.

---

## 5. 🧠 Daily SRS Training
When you are ready to practice, go to the Main Window and click **"Training starten"**:

- **New Mode ("Neue Züge")**: Teaches you unlearned repertoire moves, starting with the most critical and high-priority lines.
- **Due Mode ("Wiederholen")**: Reviews moves scheduled for today based on the **Leitner 7-Box SRS algorithm**.
- **Course Splash Screen**: When starting a brand-new repertoire, a splash window displays your course goals and statistics. Click **"JETZT LERNEN"** to begin.
- **Variation Filters**: Focus your training on a specific variation (e.g., practice only the *"Grand Prix Attack"*) using the variation dropdown menu.
- **Freies Training**: Practice moves freely without affecting your profile's SRS due dates.

---

## 6. 🌐 Lichess Integration & Microscope Analysis
- **Lichess API Token**: Add your token in the Repertoire Settings for unlimited stats access and username verification.
- **Microscope Button**: Click the 🔬 **Microscope Icon** on the board at any time to open the current position on Lichess in your default browser for deeper exploratory analysis.
- **Multilingual Notation**: Toggle between English (`Nf3`) and German (`Sf3`) move notation at any time in your profile settings.

---
*Happy Training! If you have technical questions about move selection or priority scores, check out [TECHNICAL_DEEP_DIVE.md](TECHNICAL_DEEP_DIVE.md).*
