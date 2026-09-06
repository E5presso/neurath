"""One reproducible development check, also used by the self-installed harness."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = (
    ('Distribution integrity', ['-m', 'neurath', 'integrity']),
    ('Python diagnostics', ['-m', 'ruff', 'check', 'src/neurath', '--select', 'E4,E7,E9,F']),
    ('Package and installation tests', ['-m', 'pytest', '-q']),
    ('Runtime contracts', ['tools/run_core_regressions.py']),
)


def main():
    for name, args in STEPS:
        print(f'\n{name}', flush=True)
        result = subprocess.run([sys.executable, *args], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    print('NEURATH_CHECK_OK', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
