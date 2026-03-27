import pytest
import chess
from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.creator.creator_window import CreatorBackend

class TestInheritance:
    @pytest.fixture(autouse=True)
    def setup_backend(self, mock_user_dir):
        """Setup a clean CreatorBackend for the tests in this class."""
        self.backend = CreatorBackend()
        self.backend.load_repertoire("InheritanceTest")
        # Add standard levels
        self.backend.session.add(RepertoireLevel(name="Main", order=1))
        self.backend.session.add(RepertoireLevel(name="Side", order=2))
        self.backend.session.add(RepertoireLevel(name="Deep", order=3))
        self.backend.session.commit()

    def test_basic_variation_inheritance(self):
        """Test that names propagate down a single line."""
        start_fen = chess.STARTING_FEN
        
        # 1. Name the first move
        self.backend.update_position_data(start_fen, "Start", "Sicilian", "", "")
        
        # 2. Add a move (1. e4)
        self.backend.add_move(start_fen, "e2e4", "e4", level_order=1)
        e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
        
        # 3. Check if 1. e4 inherited the name
        data = self.backend.get_position_data(e4_fen)
        assert data["variation_1"] == "Sicilian"
        assert data["v1_inherited"] is True

    def test_overwriting_inheritance(self):
        """Test that explicitly setting a name stops inheritance from above."""
        start_fen = chess.STARTING_FEN
        self.backend.update_position_data(start_fen, "", "Open Game", "", "")
        
        # Add 1. e4
        self.backend.add_move(start_fen, "e2e4", "e4", level_order=1)
        e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
        
        # Overwrite name at 1. e4
        self.backend.update_position_data(e4_fen, "", "Sicilian Defense", "", "")
        
        # Add 1... c5
        board = chess.Board(e4_fen)
        board.push_uci("c7c5")
        c5_fen = board.fen()
        self.backend.add_move(e4_fen, "c7c5", "c5", level_order=1)
        
        # Check inheritance
        data = self.backend.get_position_data(c5_fen)
        assert data["variation_1"] == "Sicilian Defense"
        assert data["v1_inherited"] is True

    def test_transposition_priority_inheritance(self):
        """Test that transpositions inherit from the highest priority parent."""
        # Path A: 1. e4 e6 (Priority 1.0) - "French"
        # Path B: 1. d4 e6 2. e4 (Priority 0.5) - "Queen's Pawn"
        
        start_fen = chess.STARTING_FEN
        
        # Setup Path A
        self.backend.add_move(start_fen, "e2e4", "e4", level_order=1)
        e4_move = self.backend.session.query(Move).filter_by(uci="e2e4").first()
        e4_move.priority_score = 1.0
        e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
        self.backend.update_position_data(e4_fen, "", "French Defense", "", "")
        
        # Setup Path B
        self.backend.add_move(start_fen, "d2d4", "d4", level_order=1)
        d4_move = self.backend.session.query(Move).filter_by(uci="d2d4").first()
        d4_move.priority_score = 0.5
        d4_fen = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq -"
        self.backend.update_position_data(d4_fen, "", "Queen's Pawn", "", "")
        
        # Reach same position (1. e4 e6 and 1. d4 e6 2. e4)
        target_fen = "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
        self.backend.add_move(e4_fen, "e7e6", "e6", level_order=1)
        self.backend.add_move(d4_fen, "e7e6", "e6", level_order=1)
        self.backend.add_move("rnbqkbnr/pppp1ppp/4p3/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq -", "e2e4", "e4", level_order=1)
        
        # The target position should inherit "French Defense" because Path A has higher priority (1.0 vs 0.5)
        data = self.backend.get_position_data(target_fen)
        assert data["variation_1"] == "French Defense"

    def test_robust_level_assignment(self):
        """
        Test the complex logic for assigning levels to new moves across multiple levels.
        Covers:
        1. First move in a repo (Level 1)
        2. Sibling move (Max Level)
        3. Child of Main Line (Parent Inheritance)
        4. Child of Side Line (Parent Inheritance)
        5. Transposition merge (Consensus Rule check)
        """
        start_fen = chess.STARTING_FEN
        
        # 1. Add first move (Main Line)
        # Scenario: Repo is empty. 1. e4 is added.
        self.backend.add_move(start_fen, "e2e4", "e4")
        e4_rm = self.backend.session.query(RepertoireMove).join(Move).filter(Move.uci=="e2e4").first()
        assert e4_rm.level == 1, "First move in repo should default to Level 1"
        
        # 2. Add sibling move (Alternative)
        # Scenario: 1. e4 exists. Adding 1. d4.
        self.backend.add_move(start_fen, "d2d4", "d4")
        d4_rm = self.backend.session.query(RepertoireMove).join(Move).filter(Move.uci=="d2d4").first()
        assert d4_rm.level == 3, "Sibling move should get highest level in DB (Level 3)"
        
        # 3. Add child of Main Line
        # Scenario: 1. e4 (Level 1) -> 1... e5 is added.
        e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
        self.backend.add_move(e4_fen, "e7e5", "e5")
        e5_rm = self.backend.session.query(RepertoireMove).join(Move).filter(Move.uci=="e7e5").first()
        assert e5_rm.level == 1, "Child should inherit level 1 from Main Line parent"
        
        # 4. Add child of Side Line
        # Scenario: 1. d4 (Level 3) -> 1... d5 is added.
        d4_fen = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq -"
        self.backend.add_move(d4_fen, "d7d5", "d5")
        d5_rm = self.backend.session.query(RepertoireMove).join(Move).filter(Move.uci=="d7d5").first()
        assert d5_rm.level == 3, "Child should inherit level 3 from Side Line parent"
        
        # 5. Adding a move that creates a new sibling in a sub-branch
        # Scenario: 1. e4 e5 (Level 1) -> adding 1... c5 as sibling.
        self.backend.add_move(e4_fen, "c7c5", "c5")
        c5_rm = self.backend.session.query(RepertoireMove).join(Move).filter(Move.uci=="c7c5").first()
        assert c5_rm.level == 3, "New sibling in sub-branch should get max level (3)"

    def test_consensus_level_cascade(self):
        """
        Test that updating a move's level cascades to descendants 
        ONLY if there is no conflict from other incoming paths.
        """
        start_fen = chess.STARTING_FEN
        
        # Path 1: 1. e4 (Level 1) -> 1... e6 (Level 1) -> 2. d4 (Level 1)
        self.backend.add_move(start_fen, "e2e4", "e4", level_order=1)
        e4_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
        self.backend.add_move(e4_fen, "e7e6", "e6", level_order=1)
        e6_fen = "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
        self.backend.add_move(e6_fen, "d2d4", "d4", level_order=1)
        d4_move_id = self.backend.session.query(Move).filter(Move.from_position.has(fen=e6_fen), Move.uci=="d2d4").first().id
        
        # Path 2: 1. d4 (Level 2) -> 1... e6 (Level 2) -> 2. e4 (Level 2 - Transposition)
        self.backend.add_move(start_fen, "d2d4", "d4", level_order=2)
        d4_fen = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq -"
        self.backend.add_move(d4_fen, "e7e6", "e6", level_order=2)
        # The move 2. e4 already exists (from Path 1), reaching the same destination
        self.backend.add_move(e6_fen, "d2d4", "d4", level_order=2) # This is 2. d4 in Path 2
        
        # Initially, 2. d4 should remain at Level 1 (from Path 1)
        rm_d4 = self.backend.session.query(RepertoireMove).filter_by(move_id=d4_move_id).first()
        assert rm_d4.level == 1
        
        # NOW: Update the parent 1... e6 in Path 1 to Level 2
        e6_move_id = self.backend.session.query(Move).filter(Move.from_position.has(fen=e4_fen), Move.uci=="e7e6").first().id
        self.backend.update_move_level(e6_move_id, 2)
        
        # Since BOTH paths leading to 2. d4 are now Level 2 (Consensus reached!), 
        # the level of 2. d4 should have cascaded to Level 2.
        rm_d4_after = self.backend.session.query(RepertoireMove).filter_by(move_id=d4_move_id).first()
        assert rm_d4_after.level == 2, "Level should have cascaded due to consensus"

    def test_invalid_move_addition(self):
        """Test input validation when adding an invalid move."""
        start_fen = chess.STARTING_FEN
        # Adding a move with invalid characters or illegal move for this position
        # Note: CreatorBackend.add_move might handle this gracefully or throw.
        # Let's see how it behaves with an illegal move.
        try:
            self.backend.add_move(start_fen, "e2e5", "e5") # Illegal move
        except Exception:
            pass # Expecting a failure or graceful handle
        
        # The move should not be in the database
        move_check = self.backend.session.query(Move).filter_by(uci="e2e5").first()
        assert move_check is None
