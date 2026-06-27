import pytest
from unittest.mock import MagicMock, patch, ANY
import chess
import chess.engine
import time
from opening_fenix.core.engine import EngineThread

@pytest.fixture
def mock_engine_thread():
    # We patch QThread and pyqtSignal to avoid needing a full Qt environment for most tests
    with patch('opening_fenix.core.engine.QThread'), \
         patch('opening_fenix.core.engine.pyqtSignal'):
        thread = EngineThread(engine_path="fake/path", threads=2, depth=10, multipv=2)
        # Manually mock the signals since we patched pyqtSignal
        thread.info_signal = MagicMock()
        thread.db_update_signal = MagicMock()
        return thread

def test_engine_init(mock_engine_thread):
    assert mock_engine_thread.engine_path == "fake/path"
    assert mock_engine_thread.threads == 2
    assert mock_engine_thread.target_depth == 10
    assert mock_engine_thread.multipv == 2
    assert mock_engine_thread.running is False

def test_start_engine_success(mock_engine_thread):
    with patch('chess.engine.SimpleEngine.popen_uci') as mock_popen:
        mock_engine = MagicMock()
        mock_engine.options = {"Threads": True}
        mock_popen.return_value = mock_engine
        
        mock_engine_thread.start_engine()
        
        mock_popen.assert_called_once()
        mock_engine.configure.assert_called_with({"Threads": 2})
        assert mock_engine_thread.running is True
        mock_engine_thread.info_signal.emit.assert_any_call(["Engine bereit."])

def test_start_engine_failure(mock_engine_thread):
    with patch('chess.engine.SimpleEngine.popen_uci', side_effect=Exception("Failed to load")):
        mock_engine_thread.start_engine()
        mock_engine_thread.info_signal.emit.assert_called_with(["Engine Fehler: Failed to load"])
        assert mock_engine_thread.running is False

def test_stop_engine(mock_engine_thread):
    mock_engine = MagicMock()
    mock_engine_thread.engine = mock_engine
    mock_engine_thread.running = True
    
    mock_engine_thread.stop_engine()
    
    mock_engine.quit.assert_called_once()
    assert mock_engine_thread.engine is None
    assert mock_engine_thread.running is False
    assert mock_engine_thread.is_active is False

def test_set_position(mock_engine_thread):
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    mock_engine_thread.set_position(fen)
    assert mock_engine_thread._target_fen == fen
    assert isinstance(mock_engine_thread.board, chess.Board)
    
    # Test deduplication
    mock_engine_thread.board = "marker"
    mock_engine_thread.set_position(fen)
    assert mock_engine_thread.board == "marker" # Should not have changed

def test_toggle_analysis(mock_engine_thread):
    mock_engine_thread._target_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    
    # Toggle on
    mock_engine_thread.toggle_analysis(True)
    assert mock_engine_thread.is_active is True
    assert isinstance(mock_engine_thread.board, chess.Board)
    
    # Toggle off
    mock_engine_thread.toggle_analysis(False)
    assert mock_engine_thread.is_active is False
    
    # Toggle off again (no change)
    mock_engine_thread.toggle_analysis(False)
    assert mock_engine_thread.is_active is False

def test_update_config(mock_engine_thread):
    mock_engine = MagicMock()
    mock_engine.options = {"Threads": True}
    mock_engine_thread.engine = mock_engine
    
    # Update without engine change (only depth/limit)
    mock_engine_thread.update_config(threads=2, depth=20, use_depth_limit=True, multipv=2)
    assert mock_engine_thread.target_depth == 20
    mock_engine.configure.assert_not_called()
    
    # Update with engine change (threads/multipv)
    mock_engine_thread.update_config(threads=4, depth=20, use_depth_limit=True, multipv=3)
    assert mock_engine_thread.threads == 4
    assert mock_engine_thread.multipv == 3
    mock_engine.configure.assert_called_with({"Threads": 4})

def test_process_info_throttling(mock_engine_thread):
    mock_engine_thread._emit_interval = 100 # ms
    mock_engine_thread._throttle_timer = MagicMock()
    board = chess.Board()
    
    info = {"multipv": 1, "score": chess.engine.PovScore(chess.engine.Cp(100), chess.WHITE)}
    
    with patch.object(mock_engine_thread, '_emit_current_cache') as mock_emit:
        # Before interval
        mock_engine_thread._throttle_timer.hasExpired.return_value = False
        mock_engine_thread.process_info(info, board)
        mock_emit.assert_not_called()
        assert mock_engine_thread.lines_cache[1] == info
            
        # After interval
        mock_engine_thread._throttle_timer.hasExpired.return_value = True
        mock_engine_thread.process_info(info, board)
        mock_emit.assert_called_once_with(board)
        mock_engine_thread._throttle_timer.restart.assert_called_once()

def test_extract_line_data_mate(mock_engine_thread):
    board = chess.Board()
    info = {
        "score": chess.engine.PovScore(chess.engine.Mate(1), chess.WHITE),
        "pv": [chess.Move.from_uci("e2e4")],
        "depth": 10
    }
    extracted = mock_engine_thread._extract_line_data(info, board)
    assert extracted["score"] == "M+1"
    assert extracted["cp_val"] == 10000
    assert extracted["pv"] == "e4"
    assert extracted["depth"] == 10

def test_extract_line_data_cp(mock_engine_thread):
    board = chess.Board()
    info = {
        "score": chess.engine.PovScore(chess.engine.Cp(-50), chess.WHITE),
        "pv": [chess.Move.from_uci("g1f3")],
        "depth": 15
    }
    extracted = mock_engine_thread._extract_line_data(info, board)
    assert extracted["score"] == "-0.50"
    assert extracted["cp_val"] == -50
    assert extracted["pv"] == "Nf3"

def test_emit_current_cache(mock_engine_thread):
    board = chess.Board()
    mock_engine_thread.multipv = 2
    mock_engine_thread.lines_cache = {
        1: {"score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE), "depth": 10, "pv": []},
        2: {"score": chess.engine.PovScore(chess.engine.Cp(20), chess.WHITE), "depth": 11, "pv": []},
        3: {"score": chess.engine.PovScore(chess.engine.Cp(30), chess.WHITE), "depth": 12, "pv": []}
    }
    
    mock_engine_thread._emit_current_cache(board)
    
    # Should only emit first 2 lines
    assert mock_engine_thread.info_signal.emit.called
    emitted_lines = mock_engine_thread.info_signal.emit.call_args[0][0]
    assert len(emitted_lines) == 2
    
    # Should emit db update for best line
    mock_engine_thread.db_update_signal.emit.assert_called_with(board.fen(), 10, 10)

def test_run_loop_basic(mock_engine_thread):
    # This is a bit tricky to test because it's a loop.
    # We can use a side effect to set running=False after one iteration.
    
    mock_engine_thread.running = True
    mock_engine_thread.is_active = True
    mock_engine_thread.board = chess.Board()
    mock_engine_thread._target_fen = mock_engine_thread.board.fen()
    
    mock_engine = MagicMock()
    mock_engine_thread.engine = mock_engine
    
    # Mock the analysis context manager
    analysis_mock = MagicMock()
    analysis_mock.__enter__.return_value = [{"multipv": 1, "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE)}]
    mock_engine.analysis.return_value = analysis_mock
    
    # Patch start_engine to not do anything (already mocked what we need)
    # and msleep to be fast
    with patch.object(mock_engine_thread, 'start_engine'), \
         patch.object(mock_engine_thread, 'stop_engine'), \
         patch.object(mock_engine_thread, 'msleep'):
         
        # Make the loop run only once
        def stop_after_once(*args, **kwargs):
            mock_engine_thread.running = False
            return analysis_mock
            
        mock_engine.analysis.side_effect = stop_after_once
        
        mock_engine_thread.run()
        
        mock_engine.analysis.assert_called()
        mock_engine_thread.info_signal.emit.assert_any_call(["Engine-Thread gestartet."])
