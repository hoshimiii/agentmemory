import sys

sys.dont_write_bytecode = True

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agentmemory.cli import run

if __name__ == "__main__":
    sys.exit(run())
