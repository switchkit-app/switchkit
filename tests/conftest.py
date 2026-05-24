import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent
FIXTURE_DB = FIXTURE_DIR / "plex-test.db"

def pytest_configure(config):
    """Auto-generate test fixture if missing."""
    if not FIXTURE_DB.exists():
        import subprocess
        res = subprocess.run(
            [sys.executable, str(FIXTURE_DIR / "generate_fixture.py")],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print(f"FAILED TO GENERATE FIXTURE: {res.stderr}", file=sys.stderr)
            sys.exit(res.returncode)
