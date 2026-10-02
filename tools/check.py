"""Reproducible full check, with explicit subsets for focused development."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKERS = min(8, os.cpu_count() or 1)


def worker_count(value):
    count = int(value)
    if count < 0:
        raise argparse.ArgumentTypeError("workers must be zero (serial) or positive")
    return count


def steps(suite, workers):
    pytest = ['-m', 'pytest', '-q', '-x', '-n', str(workers), '--dist', 'load', '--durations=10']
    if suite == 'all':
        yield 'Package version consistency', ['tools/versioning.py', '--check']
        yield 'Distribution integrity', ['-m', 'neurath', 'integrity']
        yield 'Python diagnostics', ['-m', 'ruff', 'check', 'src/neurath', '--select', 'E4,E7,E9,F']
    if suite == 'fast':
        yield 'Fast contract tests (partial check)', [*pytest, '-m', 'fast']
    elif suite in ('all', 'package'):
        yield 'Package and installation tests', pytest
    if suite in ('all', 'runtime'):
        yield 'Runtime contracts', ['tools/run_core_regressions.py', '--workers', str(workers)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('all', 'fast', 'package', 'runtime'), default='all',
                        help='all is the required check; other selections are partial')
    parser.add_argument('--workers', type=worker_count,
                        help='pytest workers; default: serial for fast, up to eight otherwise')
    args = parser.parse_args(argv)
    workers = args.workers if args.workers is not None else (0 if args.suite == 'fast' else DEFAULT_WORKERS)
    started = time.monotonic()
    for name, command in steps(args.suite, workers):
        print(f'\n{name}', flush=True)
        result = subprocess.run([sys.executable, *command], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    marker = 'NEURATH_CHECK_OK' if args.suite == 'all' else f'NEURATH_PARTIAL_CHECK_OK suite={args.suite}'
    print(f'{marker} ({time.monotonic() - started:.1f}s)', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
