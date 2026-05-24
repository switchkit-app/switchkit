import subprocess
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent
GENERATOR = FIXTURE_DIR / "generate_fixture.py"


def pytest_configure(config):
    """Regenerate test fixture before each test run."""
    # Under pytest-xdist, only the controller (master) generates the
    # fixture. Workers skip regeneration to avoid N concurrent processes
    # writing the same database file.
    if hasattr(config, "workerinput"):
        return
    res = subprocess.run(
        [sys.executable, str(GENERATOR)],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print(f"FAILED TO GENERATE FIXTURE: {res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)
