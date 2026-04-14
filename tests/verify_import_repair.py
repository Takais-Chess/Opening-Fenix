import os
import shutil
import chess.pgn
import io
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from opening_fenix.core.db.models import Base, Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.services.import_service import import_pgn_to_db
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path

def test_import_no_holes():
    repo_name = "Test_Import_Repair"
    # Clean up old test data if any
    db_path = get_repertoire_db_path(repo_name)
    if os.path.exists(os.path.dirname(db_path)):
        shutil.rmtree(os.path.dirname(db_path))

    # Create dummy PGN
    pgn_text = """[Event "Test"]
[Site "?"]
[Date "????.??.??"]
[Round "?"]
[White "Player"]
[Black "Opponent"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 *
"""
    pgn_path = "test_import.pgn"
    with open(pgn_path, "w") as f:
        f.write(pgn_text)

    print(f"Importing PGN into {repo_name} as White (Level 1)...")
    success, msg = import_pgn_to_db(pgn_path, repo_name, "w", "Grundlagen", 1)
    
    print(f"Import result: {success}, {msg}")
    
    if success:
        from opening_fenix.core.db.database import DatabaseManager
        db = DatabaseManager(db_path)
        session = db.get_session()
        
        # Check total repertoire moves
        # Moves are: e4, e5, Nf3, Nc6, Bb5 (Total 5)
        # Previously only e4, Nf3, Bb5 (3) would be in repertoire
        count = session.query(RepertoireMove).count()
        print(f"Total repertoire moves in DB: {count}")
        
        # Verify no gaps
        subq = session.query(Move.from_position_id).join(RepertoireMove, Move.id == RepertoireMove.move_id).distinct().subquery()
        gaps = session.query(Move).outerjoin(RepertoireMove, Move.id == RepertoireMove.move_id)\
            .filter(RepertoireMove.id == None)\
            .filter(Move.to_position_id.in_(subq)).all()
        
        print(f"Gaps found: {len(gaps)}")
        
        if count == 5 and len(gaps) == 0:
            print("SUCCESS: No holes created and all moves included.")
        else:
            print("FAILURE: Expected 5 moves and 0 gaps.")
        
        session.close()
        db.close()
    
    # Clean up
    if os.path.exists(pgn_path): os.remove(pgn_path)
    if os.path.exists(os.path.dirname(db_path)):
        shutil.rmtree(os.path.dirname(db_path))

if __name__ == "__main__":
    test_import_no_holes()
