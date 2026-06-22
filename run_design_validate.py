import sys
sys.path.insert(0, r"C:\Data_unsynced\git_repos\AIgen\skills\sdlc\skills\design")
from pathlib import Path
import validate_schema
sys.exit(validate_schema.validate_all(Path(r"C:\Data_unsynced\git_repos\AIgen\skills\sdlc-design-workspace\iteration-1\eval-1-game-dual-axis\test-project\docs\DESIGN.yaml")))
