"""Engineering Health Intelligence System - single entry point. See `python run.py --help`."""
import sys

from src.orchestration.cli import main

if __name__ == "__main__":
    sys.exit(main())
