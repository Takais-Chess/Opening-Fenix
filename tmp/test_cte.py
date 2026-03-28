import sqlite3
import chess

def test():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE moves (id INT, from_position_id INT, to_position_id INT, san TEXT, uci TEXT)')
    conn.execute('CREATE TABLE positions (id INT, fen TEXT, comment TEXT)')
    
    # 1. d4 Nf6 (pos 1, 2)
    # 1. c4 Nf6 (pos 3, 2) -- Transposition at pos 2
    conn.execute('INSERT INTO moves VALUES (1, 0, 1, "d4", "d2d4")')
    conn.execute('INSERT INTO moves VALUES (2, 1, 2, "Nf6", "g8f6")')
    conn.execute('INSERT INTO moves VALUES (3, 0, 3, "c4", "c2c4")')
    conn.execute('INSERT INTO moves VALUES (4, 3, 2, "Nf6", "g8f6")')
    
    # Move from pos 2 to pos 4 (e.g. 3. d5)
    conn.execute('INSERT INTO moves VALUES (5, 2, 4, "d5", "d4d5")')
    
    conn.execute('INSERT INTO positions VALUES (1, "FEN1", "pp1")')
    conn.execute('INSERT INTO positions VALUES (2, "FEN2", "pp2")')
    conn.execute('INSERT INTO positions VALUES (3, "FEN3", "pp3")')
    conn.execute('INSERT INTO positions VALUES (4, "FEN4", "pp4")')
    
    # Target move 5. It has TWO parents (2 and 4).
    move_id = 5
    query = """
        WITH RECURSIVE ancestors(id, from_id, to_id, uci, san, level) AS (
            SELECT id, from_position_id, to_position_id, uci, san, 0
            FROM moves
            WHERE id = ?
            UNION ALL
            SELECT m.id, m.from_position_id, m.to_position_id, m.uci, m.san, a.level + 1
            FROM moves m
            JOIN ancestors a ON m.to_position_id = a.from_id
            LIMIT 50
        )
        SELECT a.*, p.fen FROM ancestors a JOIN positions p ON a.to_id = p.id ORDER BY a.level DESC
    """
    
    results = conn.execute(query, (move_id,)).fetchall()
    print("History for move 5:")
    for r in results:
        print(r)

if __name__ == "__main__":
    test()
