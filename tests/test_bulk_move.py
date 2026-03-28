import os
import sys

# Ensure the project root is in the path
sys.path.append(os.getcwd())

from opening_fenix.core.services.repertoire_service import RepertoireManager
from opening_fenix.core.db.models import RepertoireMove

def test_bulk_move():
    manager = RepertoireManager()
    repo_name = "1.e4 Empfelung Anfänger"
    
    # Check if repo exists
    repos = manager.get_all_repertoires()
    if repo_name not in repos:
        print(f"Error: {repo_name} not found in {repos}")
        return

    print(f"Testing bulk move for {repo_name}...")
    manager.set_active_repertoire(repo_name)
    
    # Get initial levels
    moves = manager.core.get_all_active_repertoire_moves()
    if not moves:
        print("No active moves found in the repertoire for testing.")
        return
        
    initial_levels = [m.level for m in moves]
    print(f"Found {len(moves)} moves. Initial levels: {set(initial_levels)}")
    
    # Target level (let's use 2 as a test target)
    target_level = 2
    
    print(f"Moving all moves to level {target_level}...")
    count = manager.move_all_to_level(target_level)
    print(f"Backend reported {count} moves updated.")
    
    # Verify
    updated_moves = manager.core.get_all_active_repertoire_moves()
    final_levels = [m.level for m in updated_moves]
    
    success = all(level == target_level for level in final_levels)
    if success:
        print("Verification SUCCESS: All moves moved to level 2.")
    else:
        print(f"Verification FAILED: Found levels {set(final_levels)}")
    
    manager.close()

if __name__ == "__main__":
    test_bulk_move()
