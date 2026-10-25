"""Generate platform/Python-aware locks with uv (run from the repository root)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3].absolute()
REQUIREMENTS = ROOT / "requirements"

for source in [REQUIREMENTS / "base.in", *sorted(REQUIREMENTS.glob("extra-*.in"))]:
    subprocess.check_call(
        [
            "uv",
            "pip",
            "compile",
            str(source.relative_to(ROOT)),
            "--python-version",
            "3.8.1",
            "--universal",
            "--no-python-downloads",
            "--output-file",
            str(source.with_suffix(".txt").relative_to(ROOT)),
            "--no-header",
            *sys.argv[1:],
        ],
        cwd=ROOT,
    )
