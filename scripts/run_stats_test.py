import pytest
import sys
import os

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, project_root)
    os.chdir(project_root)
    exit_code = pytest.main(["-v", "tests/test_stats_update.py", "tests/conftest.py"])
    sys.exit(exit_code)
