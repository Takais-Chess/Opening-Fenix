import pytest
import sys
import os

# Set environment to mock directory for testing
os.environ["PYTEST_CURRENT_TEST"] = "1"

if __name__ == "__main__":
    # Current script is in scripts/
    # Project root is one level up
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    sys.path.insert(0, project_root)
    os.chdir(project_root)
    
    # Run pytest on the new intensive test file
    # We include tests/conftest.py to ensure fixtures like mock_user_dir are available
    exit_code = pytest.main(["-v", "tests/test_intensive_inheritance.py", "tests/conftest.py"])
    sys.exit(exit_code)
