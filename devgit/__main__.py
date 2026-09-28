import sys
from pathlib import Path

# Ensure devgit parent directory is on sys.path
parent = str(Path(__file__).resolve().parent.parent)
if parent not in sys.path:
    sys.path.insert(0, parent)

from devgit.server import main

if __name__ == "__main__":
    main()
