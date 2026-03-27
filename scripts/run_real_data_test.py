import pytest
import sys
import os

if __name__ == "__main__":
    # Current script is in scripts/
    # Project root is one level up
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, project_root)
    os.chdir(project_root)
    
    # Run the test specifically on the real 1.e4 database copy
    exit_code = pytest.main(["-v", "-s", "tests/test_real_database_inheritance.py", "tests/conftest.py"])
    sys.exit(exit_code)
