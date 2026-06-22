import sys
import os

skill_dir = r"C:\Data_unsynced\git_repos\AIgen\skills\sdlc\skills\design"
design_path = r"C:\Data_unsynced\git_repos\AIgen\skills\sdlc-design-workspace\iteration-1\eval-1-game-dual-axis\test-project\docs\DESIGN.yaml"

sys.path.insert(0, skill_dir)
from pathlib import Path
import validate_schema as vs

result = vs.validate_all(Path(design_path))
print(f"VALIDATOR_EXIT_CODE={result}", file=sys.stderr)
sys.exit(result)
