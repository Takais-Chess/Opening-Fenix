import pytest
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel

class TestLevelDeleteAndPopularityPrune:
    @pytest.fixture
    def backend(self, mock_user_dir):
        backend = CreatorBackend()
        backend.load_repertoire("test_delete_and_prune")
        
        # Clean start: add 3 levels
        backend.session.query(RepertoireMove).delete()
        backend.session.query(Move).delete()
        backend.session.query(Position).delete()
        backend.session.query(RepertoireLevel).delete()
        
        backend.session.add(RepertoireLevel(name="Level 1", order=1))
        backend.session.add(RepertoireLevel(name="Level 2", order=2))
        backend.session.add(RepertoireLevel(name="Level 3", order=3))
        backend.session.commit()
        
        yield backend
        backend.close()

    def test_delete_repertoire_level_reassignment(self, backend):
        # Add positions & moves across level 1, 2, and 3
        pos_start = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        pos_e4 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP2PP/RNBQKBNR b KQkq e3 0 1")
        pos_d4 = Position(fen="rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 1")
        pos_c4 = Position(fen="rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq c3 0 1")
        backend.session.add_all([pos_start, pos_e4, pos_d4, pos_c4])
        backend.session.commit()

        move_e4 = Move(from_position_id=pos_start.id, to_position_id=pos_e4.id, uci="e2e4", san="e4", priority_score=0.5)
        move_d4 = Move(from_position_id=pos_start.id, to_position_id=pos_d4.id, uci="d2d4", san="d4", priority_score=0.3)
        move_c4 = Move(from_position_id=pos_start.id, to_position_id=pos_c4.id, uci="c2c4", san="c4", priority_score=0.1)
        backend.session.add_all([move_e4, move_d4, move_c4])
        backend.session.commit()

        rm_e4 = RepertoireMove(move_id=move_e4.id, level=1)
        rm_d4 = RepertoireMove(move_id=move_d4.id, level=2)
        rm_c4 = RepertoireMove(move_id=move_c4.id, level=3)
        backend.session.add_all([rm_e4, rm_d4, rm_c4])
        backend.session.commit()

        # Delete Level 2 (reassign moves to Level 1)
        success, msg = backend.delete_repertoire_level(level_order=2, target_level_order=1)
        assert success is True

        # Verify levels remaining
        levels = backend.get_repertoire_levels()
        assert len(levels) == 2
        assert levels[0]['order'] == 1
        assert levels[1]['order'] == 2

        # Verify move_d4 (previously Level 2) is now assigned to Level 1
        rm_d4_check = backend.session.query(RepertoireMove).filter_by(move_id=move_d4.id).first()
        assert rm_d4_check.level == 1

        # Verify move_c4 (previously Level 3) shifted to Level 2
        rm_c4_check = backend.session.query(RepertoireMove).filter_by(move_id=move_c4.id).first()
        assert rm_c4_check.level == 2

    def test_low_popularity_prune(self, backend):
        pos_start = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        pos_e4 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP2PP/RNBQKBNR b KQkq e3 0 1")
        pos_h3 = Position(fen="rnbqkbnr/pppppppp/8/8/7P/8/PPPPPPP1/RNBQKBNR b KQkq h3 0 1")
        backend.session.add_all([pos_start, pos_e4, pos_h3])
        backend.session.commit()

        # High priority move (60%) vs low priority move (2%)
        move_e4 = Move(from_position_id=pos_start.id, to_position_id=pos_e4.id, uci="e2e4", san="e4", priority_score=0.6)
        move_h3 = Move(from_position_id=pos_start.id, to_position_id=pos_h3.id, uci="h2h3", san="h3", priority_score=0.02)
        backend.session.add_all([move_e4, move_h3])
        backend.session.commit()

        rm_e4 = RepertoireMove(move_id=move_e4.id, level=1)
        rm_h3 = RepertoireMove(move_id=move_h3.id, level=1)
        backend.session.add_all([rm_e4, rm_h3])
        backend.session.commit()

        move_e4_id = move_e4.id
        move_h3_id = move_h3.id

        # Test Impact calculation for threshold 5%
        m_cnt, p_cnt = backend.get_low_popularity_prune_impact(threshold_pct=5)
        assert m_cnt == 1

        # Execute Prune
        deleted_count = backend.apply_low_popularity_prune(threshold_pct=5)
        assert deleted_count == 1

        # Move e4 remains, move h3 deleted
        assert backend.session.query(Move).filter_by(id=move_e4_id).first() is not None
        assert backend.session.query(Move).filter_by(id=move_h3_id).first() is None

    def test_delete_highest_level_with_move_deletion(self, backend):
        pos_start = Position(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        pos_e4 = Position(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP2PP/RNBQKBNR b KQkq e3 0 1")
        pos_c4 = Position(fen="rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq c3 0 1")
        backend.session.add_all([pos_start, pos_e4, pos_c4])
        backend.session.commit()

        move_e4 = Move(from_position_id=pos_start.id, to_position_id=pos_e4.id, uci="e2e4", san="e4", priority_score=0.5)
        move_c4 = Move(from_position_id=pos_start.id, to_position_id=pos_c4.id, uci="c2c4", san="c4", priority_score=0.1)
        backend.session.add_all([move_e4, move_c4])
        backend.session.commit()

        rm_e4 = RepertoireMove(move_id=move_e4.id, level=1)
        rm_c4 = RepertoireMove(move_id=move_c4.id, level=3) # Highest level
        backend.session.add_all([rm_e4, rm_c4])
        backend.session.commit()

        move_e4_id = move_e4.id
        move_c4_id = move_c4.id

        # Delete highest level (Level 3) with delete_moves=True
        success, msg = backend.delete_repertoire_level(level_order=3, target_level_order=None, delete_moves=True)
        assert success is True

        # Level 3 is gone, 2 levels remain
        levels = backend.get_repertoire_levels()
        assert len(levels) == 2

        # Level 1 move remains, Level 3 move is deleted
        assert backend.session.query(Move).filter_by(id=move_e4_id).first() is not None
        assert backend.session.query(Move).filter_by(id=move_c4_id).first() is None
