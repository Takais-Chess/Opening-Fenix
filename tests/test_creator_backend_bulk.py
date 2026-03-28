import os
import sys
import tempfile

# Ensure the project root is in the path
sys.path.append(os.getcwd())

from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Base, RepertoireMove, Move, Position, RepertoireLevel

def test_creator_bulk_move():
    # Use a temporary file for the database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # Create backend and initialize dummy DB
        backend = CreatorBackend()
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        
        # We need to manually initialize the DB since CreatorBackend.load_repertoire 
        # expects the DB to be in the repertoires folder.
        # Let's mock DatabaseManager to use our temp DB.
        from opening_fenix.core.db.database import DatabaseManager
        backend.db_manager = DatabaseManager(db_path, base=Base)
        backend.session = backend.db_manager.get_session()
        
        # Create schema
        Base.metadata.create_all(backend.db_manager.engine)
        
        # Add some test data
        p1 = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        p2 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
        backend.session.add_all([p1, p2])
        backend.session.flush()
        
        m1 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e2e4", san="e4")
        backend.session.add(m1)
        backend.session.flush()
        
        rm1 = RepertoireMove(move_id=m1.id, level=1)
        backend.session.add(rm1)
        
        # Add a level
        rl1 = RepertoireLevel(name="Basic", order=1)
        rl2 = RepertoireLevel(name="Advanced", order=2)
        backend.session.add_all([rl1, rl2])
        
        backend.session.commit()
        
        print("Initial state: Move e2e4 is at level 1.")
        
        # Test bulk move
        target_level = 2
        print(f"Moving all moves to level {target_level}...")
        count = backend.move_all_to_level(target_level)
        print(f"Backend reported {count} moves updated.")
        
        # Verify
        updated_rm = backend.session.query(RepertoireMove).first()
        if updated_rm.level == target_level:
            print(f"Verification SUCCESS: Move is now at level {updated_rm.level}.")
        else:
            print(f"Verification FAILED: Move is at level {updated_rm.level}.")
            
    finally:
        if backend.session: backend.session.close()
        if backend.db_manager: backend.db_manager.close()
        if os.path.exists(db_path):
            os.remove(db_path)

if __name__ == "__main__":
    test_creator_bulk_move()
