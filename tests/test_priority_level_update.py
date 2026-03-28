import pytest
import os
import shutil
import tempfile
import time
from unittest.mock import patch
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Position, Move, RepertoireMove, RepertoireLevel

class TestPriorityLevelUpdate:
    @pytest.fixture
    def backend(self, mock_user_dir):
        # mock_user_dir handles the temp directory and patching
        backend = CreatorBackend()
        
        # Ensure clean start for this specific test DB
        backend.load_repertoire("test_prio_final")
        
        # Check and add levels if missing
        existing = backend.session.query(RepertoireLevel).all()
        if not any(l.order == 1 for l in existing):
            backend.session.add(RepertoireLevel(name="Core", order=1))
        if not any(l.order == 2 for l in existing):
            backend.session.add(RepertoireLevel(name="Sideline", order=2))
        if not any(l.order == 3 for l in existing):
            backend.session.add(RepertoireLevel(name="Tricks", order=3))
        backend.session.commit()
        
        yield backend
        backend.close()

    def test_priority_upgrade_logic(self, backend):
        # 1. Setup positions and moves
        from_pos = Position(fen="start position final uniq")
        to_a = Position(fen="pos_a fen final uniq")
        to_b = Position(fen="pos_b fen final uniq")
        to_c = Position(fen="pos_c fen final uniq")
        
        backend.session.add_all([from_pos, to_a, to_b, to_c])
        backend.session.commit()
        
        # Move A: Prio 5%, Current Level 3 -> Should be upgraded to 2
        move_a = Move(from_position_id=from_pos.id, to_position_id=to_a.id, uci="e2e4", san="e4", priority_score=0.05)
        # Move B: Prio 0.5%, Current Level 3 -> Below threshold
        move_b = Move(from_position_id=from_pos.id, to_position_id=to_b.id, uci="d2d4", san="d4", priority_score=0.005)
        # Move C: Prio 5%, Current Level 1 -> Already better than 2
        move_c = Move(from_position_id=from_pos.id, to_position_id=to_c.id, uci="c2c4", san="c4", priority_score=0.05)
        
        backend.session.add_all([move_a, move_b, move_c])
        backend.session.commit()
        
        rm_a = RepertoireMove(move_id=move_a.id, level=3)
        rm_b = RepertoireMove(move_id=move_b.id, level=3)
        rm_c = RepertoireMove(move_id=move_c.id, level=1)
        
        backend.session.add_all([rm_a, rm_b, rm_c])
        backend.session.commit()
        
        # 2. Test Impact Preview
        impact = backend.get_priority_level_impact(1.0, 2)
        assert impact == 1 
        
        # 3. Apply Update
        modified = backend.apply_priority_level_update(1.0, 2)
        assert modified == 1
        
        # 4. Verify Database
        backend.session.expire_all()
        new_rm_a = backend.session.get(RepertoireMove, rm_a.id)
        assert new_rm_a.level == 2
        
        new_rm_b = backend.session.get(RepertoireMove, rm_b.id)
        assert new_rm_b.level == 3
        
        new_rm_c = backend.session.get(RepertoireMove, rm_c.id)
        assert new_rm_c.level == 1
