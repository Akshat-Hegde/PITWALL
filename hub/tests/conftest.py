import sys
from pathlib import Path

# Make tests/ importable for shared helpers (f1_helpers).
sys.path.insert(0, str(Path(__file__).parent))
