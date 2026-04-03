from opening_fenix.core.utils import get_repertoire_db_path
import pytest
import os
import chess
from opening_fenix.core.services.import_service import import_pgn_to_db
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.models import Move
from opening_fenix.core.services.tree_navigation_service import TreeNavigationService
from opening_fenix.core.utils import get_user_dir

@pytest.fixture
def temp_pgn(tmp_path):
    pgn_content = """[Event "NAG Test"]
[Site "?"]
[Date "????.??.??"]
[Round "?"]
[White "?"]
[Black "?"]
[Result "*"]

1. e4! {Excellent} e5? {Mistake} 2. Nf3!! {Brilliant} Nc6?? {Blunder} 3. Bb5!? {Interesting} a6?! {Dubious} *
"""
    pgn_file = tmp_path / "nag_test.pgn"
    pgn_file.write_text(pgn_content)
    return str(pgn_file)

def test_bulk_import_nags(mock_user_dir, temp_pgn):
    repo_name = "BulkNAGTest"
    db_path = get_repertoire_db_path(repo_name)
    
    # Ensure clean state
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # Import
    success, msg = import_pgn_to_db(temp_pgn, repo_name, "w", "Basic", 1)
    assert success is True
    
    # Verify in DB
    db = DatabaseManager(db_path)
    session = db.get_session()
    
    # Check NAGs for the moves
    # 1. e4! (NAG 1)
    move_e4 = session.query(Move).filter_by(san="e4").first()
    assert move_e4.nag == 1
    
    # 1... e5? (NAG 2)
    move_e5 = session.query(Move).filter_by(san="e5").first()
    assert move_e5.nag == 2
    
    # 2. Nf3!! (NAG 3)
    move_nf3 = session.query(Move).filter_by(san="Nf3").first()
    assert move_nf3.nag == 3
    
    # 2... Nc6?? (NAG 4)
    move_nc6 = session.query(Move).filter_by(san="Nc6").first()
    assert move_nc6.nag == 4
    
    # 3. Bb5!? (NAG 5)
    move_bb5 = session.query(Move).filter_by(san="Bb5").first()
    assert move_bb5.nag == 5
    
    # 3... a6?! (NAG 6)
    move_a6 = session.query(Move).filter_by(san="a6").first()
    assert move_a6.nag == 6
    
    # Test TreeNavigationService retrieval
    nav_service = TreeNavigationService(session)
    history = nav_service.get_history_for_move_recursive(move_a6.id)
    
    # History is [e4, e5, Nf3, Nc6, Bb5, a6]
    assert len(history) == 6
    assert history[0]['san'] == 'e4'
    assert history[0]['nag'] == 1
    assert history[1]['nag'] == 2
    assert history[2]['nag'] == 3
    assert history[3]['nag'] == 4
    assert history[4]['nag'] == 5
    assert history[5]['nag'] == 6
    
    session.close()
    db.close()
    if os.path.exists(db_path):
        os.remove(db_path)
