# Technical Deep Dive - Opening Fenix V2

This document explains the core technical logic and algorithms behind Opening Fenix V2.

## 1. Priority Scores (The BFS Probability Algorithm)
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

## 2. Level Reachability & Tree Pruning
Repertoires are organized into **Levels** (1 to N).
- During training, you can set an **Active Level** (e.g., "Level 2").
- The training manager performs a **reachability analysis**. A move is only presented if it is reachable from the root through a continuous path of moves that are **all within the active level limit**.
- This prevents the system from asking you about deep variations (Level 3) before you've learned the main lines (Level 1) that lead to them.

## 3. ELO Categories
When fetching Lichess data, the application maps your chosen category to specific rating ranges:
- **Low**: 1600
- **Mid**: 1800, 2000
- **High**: 2200
- **Masters**: Uses the dedicated Lichess Masters Explorer (Elite-level games only).

## 4. Move Processing (PGN Import)
The PGN import service uses an optimized bulk-insert strategy:
- **Deduplication**: It uses an in-memory cache of FENs and UCIs to ensure that transpositions are correctly identified as the same position, preventing duplicate entries.
- **Comment Merging**: Comments from PGN files are appended to positions. If a position appears in multiple lines with different comments, they are merged using a `|` separator.

## 5. Variation Inheritance
The variation structure (e.g., *Sicilian -> Najdorf*) is built dynamically.
- **Tag Inheritance**: If a position is tagged with a sub-variation (e.g., `variation_2 = "Najdorf"`) but is missing a top-level tag, it **recursively crawls up the tree** to find the nearest ancestor with a `variation_1` tag (e.g., "Sicilian").
- This ensures that filters in the Trainer remain consistent even if you only tag the "leaf" nodes of a variation.
