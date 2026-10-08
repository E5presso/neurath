"""Required local validation; never publishes or deploys."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for arguments in (
    ['-m', 'ruff', 'check', 'src', 'tests', '--select', 'E4,E7,E9,F'],
    ['-m', 'pytest', '-q'],
    ['-m', 'build', '--wheel', '--outdir', 'dist'],
):
    subprocess.run([sys.executable, *arguments], cwd=root, check=True)
print('NEURATH_CHECK_OK')
