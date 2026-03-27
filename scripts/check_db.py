import os
import sys

# Add the project root to sys.path so we can import opening_fenix
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.append(project_root)
os.chdir(project_root)

from opening_fenix.core.data_tools import check_all_databases_integrity, repair_all_databases_cache

if __name__ == "__main__":
    print("Prüfe Repertoire-Datenbanken...")
    report = check_all_databases_integrity()
    print("\nErgebnis-Bericht:")
    print("-" * 30)
    print(report)
    print("-" * 30)
    
    if "❌" in report:
        choice = input("\nEinige Datenbanken sind unvollständig. Möchtest du sie jetzt reparieren? (j/n): ")
        if choice.lower() == 'j':
            print("\nRepariere Datenbanken... (Dies kann einen Moment dauern)")
            repair_report = repair_all_databases_cache()
            print("\nReparatur-Bericht:")
            print("-" * 30)
            print(repair_report)
            print("-" * 30)

    input("\nDrücke Enter zum Beenden...")
