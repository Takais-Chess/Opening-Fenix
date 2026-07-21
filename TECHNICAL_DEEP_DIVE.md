# ♟️ Technical & Algorithmic Deep Dive - Opening Fenix V2

This document provides a detailed explanation of the **chess engine logic**, **graph traversal algorithms**, **priority calculation formulas**, and **training selection mechanics** behind Opening Fenix V2.

---

## 1. 📊 Priority Score Algorithm (BFS Probability Propagation)

The **Priority Score** represents the statistical probability of encountering a specific position or move in real-world play. It is calculated across the repertoire's directed acyclic move graph using a **Breadth-First Search (BFS)** traversal (`priority_service.py`).

### 1.1 Initial State & Root Setup
- The starting position (Root FEN: `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -`) is assigned an initial probability of:
  $$P(\text{Root}) = 1.0$$
- If the root position is absent, positions without incoming moves are identified as roots.

### 1.2 Probability Propagation Rules
When traversing from a position $S$ to child moves $m_1, m_2, \dots, m_k$:

1. **User's Turn**:
   If it is the user's turn, probability is divided equally among all active candidate repertoire moves:
   $$P(m_i) = \frac{P(S)}{N_{\text{active candidates}}}$$
   $$P(S_{\text{child}, i}) = P(S_{\text{child}, i}) + P(m_i)$$

2. **Opponent's Turn (Lichess Statistics)**:
   When it is the opponent's turn, probability is distributed according to Lichess population move frequencies for the chosen ELO rating tier (**Low 1600**, **Mid 1800-2000**, **High 2200**, or **Masters**):
   $$P(m_i) = P(S) \times \frac{\text{Games}(m_i)}{\sum_{j=1}^{k} \text{Games}(m_j)}$$

### 1.3 Rare Moves & Back-Propagation Weighting
To prevent unrecorded or rare opponent moves from receiving zero probability:
- **Rare Move Weight ($W_{rare}$)**: If a move is absent from the Lichess explorer, it receives a baseline weight ($W_{rare} \ge 1$).
- **Child Back-Propagation**: If an opponent move has no direct Lichess record, the service checks whether its target child position exists in Lichess data, inheriting the total game frequency of that child position as its weight.
- **Normalization**: Rare move weights are capped at $\min(\text{Lichess game counts of known moves})$ to maintain realistic proportions relative to popular lines.

---

## 2. 🎯 Next Move Selection Algorithm (`get_next_move`)

During training, the application selects the optimal move to present to the user via `TrainingManager.get_next_move()` (`training_service.py`). The selection follows a strict 4-stage hierarchy:

```
[ User Action / System Request ]
               │
               ▼
   1. Continuation Flow (Did user just succeed on move X?)
               │ (No downstream move due)
               ▼
   2. Due Mode (Review scheduled SRS moves)
               │ (No moves due)
               ▼
   3. New Mode (Learn unlearned repertoire lines)
               │ (All reachable lines learned)
               ▼
        [ Training Complete ]
```

### 2.1 Continuation Flow
If the user correctly answered move $M_{last}$:
1. The trainer queries downstream positions originating from $M_{last}.\text{to\_position\_id}$.
2. If a downstream move is due for review, it is returned immediately.
3. This creates a natural, unbroken flow through opening variations.

### 2.2 Due Mode (SRS Reviews)
1. **Time Window**: Finds all moves in `TrainingData` scheduled for review where:
   $$\text{next\_due} \le \text{Now} + 5 \text{ minutes}$$
2. **Prioritized Sorting**: Candidate due items are sorted by:
   $$\text{Sort Key} = \Big(\text{SRS Box (ASC)}, -\text{Priority Score (DESC)}\Big)$$
   *(Lower Leitner boxes are reviewed first; within the same box, higher-priority/more common lines take precedence).*
3. **Reachability & Level Validation**: Verifies that the move is reachable within the active level limit ($\text{Level}_{\text{move}} \le \text{Active Level}$).
4. **Ancestor Entry Point Resolution**: Resolves the sequence leading to the move using `_get_ancestor()` so the user is prompted from the appropriate variation boundary.

### 2.3 New Mode (Learning New Lines)
1. **Reachable Candidates**: Computes all moves reachable in the active level that have **never** been trained (`TrainingData` record absent).
2. **Highest Priority First**: Sorts unlearned candidates by `priority_score DESC`.
3. **Random Tie-Breaking**: If multiple candidate moves share the exact same top priority score, one is selected at random using `random.choice(best)`.

### 2.4 Freies Training (Free Practice)
- Runs inside an in-memory SQLite database (`:memory:`).
- Selects unlearned moves for the current session ordered by priority score, preserving actual profile progress from modification.

---

## 3. 🌐 Level Reachability & Transposition-Aware Graph Traversal

Opening Fenix uses **Level Reachability Analysis** to prevent structural inconsistencies (e.g., presenting a Level 3 variation before the user has learned the Level 1 main line leading to it).

### 3.1 Minimum Reached Level
Because positions can be reached via multiple transposition paths:
$$\text{MinReachedLevel}(P) = \min_{p \in \text{Paths}(\text{Root} \to P)} \left( \max_{m \in p} \text{Level}(m) \right)$$

### 3.2 Reachability Rule
A move $m: A \to B$ is marked as **reachable** under active level $L_{\text{active}}$ if and only if:
$$\text{MinReachedLevel}(A) \le L_{\text{active}} \quad \text{and} \quad \text{Level}(m) \le L_{\text{active}}$$

---

## 4. 🔎 Hole Finder 2.0 Algorithm (`hole_finder_service.py`)

The **Hole Finder** scans the repertoire to discover missing variations that opponents play frequently.

### 4.1 Traversal & Coverage Verification
1. Performs a BFS starting from the root FEN.
2. For each reachable position where it is the opponent's turn:
   - Queries Lichess popularity stats.
   - Calculates total opponent volume: $V_{total} = \sum \text{Games}(m_{opp})$.
   - Checks which opponent moves are covered in the repertoire.
3. **Gap Detection**: If an opponent move $m_{opp}$ has a frequency $\ge \text{Min Frequency Threshold}$ (e.g., $1.0\%$) and is **not** in the repertoire, it is flagged as an Opening Hole.

### 4.2 Transposition & Level Consistency
- Gaps are annotated with their minimum reached level.
- Double-clicking a hole in the GUI automatically navigates the board to that position and sets up candidate move additions.

---

## 5. 📈 Leitner SRS Engine & Dynamic Opening Elo

### 5.1 Leitner 7-Box Scheduling
The Spaced Repetition System uses 7 review intervals:

| Box | Review Interval | Description |
| :---: | :---: | :--- |
| **1** | 5 Minutes | Immediate review after first learning or blunder |
| **2** | 1 Day | Short-term memory consolidation |
| **3** | 3 Days | Medium-term memory test |
| **4** | 9 Days | Intermediate retention check |
| **5** | 21 Days | Long-term memory verification |
| **6** | 63 Days | Advanced mastery |
| **7** | 180 Days | Deep permanent knowledge |

When a move is answered correctly, it advances ($\text{Box} \to \text{Box} + 1$). When answered incorrectly, it drops back to **Box 1**.

### 5.2 Dynamic Opening Elo Rating
The user's overall mastery for a repertoire is calculated as an estimated **Opening Elo**:
$$\text{Opening Elo} = 1200 + \sum_{i=1}^{7} \left( \text{Count}(\text{Box}_i) \times \Delta\text{Elo}_i \right)$$
This provides immediate visual feedback on repertoire strength growth.

---

## 6. 🏗️ Architecture & Thread Management

Opening Fenix uses PySide/PyQt6 with a decoupled multi-threaded architecture (`opening_fenix/core/threads.py`):

```
                   ┌─────────────────────────┐
                   │    Qt Main GUI Loop     │
                   │ (MainWindow / Creator)  │
                   └────────────┬────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│ AnalysisThread│       │HoleFinderThread│      │LichessLoader  │
│ (Stockfish)   │       │(BFS Traversal)│       │ (API Throttling│
└───────────────┘       └───────────────┘       └───────────────┘
```

- **AnalysisThread**: Manages Stockfish UCI engine interaction with cooperative cancellation.
- **HoleFinderThread**: Runs heavy BFS scans asynchronously to keep the UI responsive.
- **LichessLoaderThread**: Handles HTTP fetching with an **Exponential Backoff Controller** (suspends for 60s on HTTP 429, gradually recovers by 5% every 50 requests).

---
*Documentation maintained for Opening Fenix V2.*
