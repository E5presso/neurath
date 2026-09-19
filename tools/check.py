"""One reproducible development check, also used by the self-installed harness."""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKERS = str(min(8, os.cpu_count() or 1))
STEPS = (
    ('Distribution integrity', ['-m', 'neurath', 'integrity']),
    ('Python diagnostics', ['-m', 'ruff', 'check', 'src/neurath', '--select', 'E4,E7,E9,F']),
    ('Package and installation tests', ['-m', 'pytest', '-q', '-x', '-n', WORKERS, '--dist', 'load', '--durations=5']),
    ('Runtime contracts', ['tools/run_core_regressions.py']),
)


def main():
    started = time.monotonic()
    for name, args in STEPS:
        print(f'\n{name}', flush=True)
        result = subprocess.run([sys.executable, *args], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    print(f'NEURATH_CHECK_OK ({time.monotonic() - started:.1f}s)', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
