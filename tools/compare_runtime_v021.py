"""Run one timing harness on the recorded 0.2 commit and the working package."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='784eb5b3612325ee6f0e3393ad4a7036b510b822')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    (root/'artifacts').mkdir(exist_ok=True)
    baseline = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options', args.baseline_ref+'^{commit}'], cwd=root, text=True).strip()
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', baseline, 'src'], cwd=root, text=True).splitlines()
    with tempfile.TemporaryDirectory(prefix='sonar-baseline-') as temporary:
        destination = Path(temporary)
        # Mechanical extraction of committed source as a disposable test fixture.
        for name in names:
            if name.endswith('.py'):
                target = destination/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(['git', 'show', baseline+':'+name], cwd=root))
        for label, package in (('baseline-v02', destination/'src'), ('current-v021', root/'src')):
            env = {**os.environ, 'PYTHONPATH': str(package),
                   'SONAR_RUNTIME_OUTPUT': str(root/'artifacts'/f'{label}-comparable.json')}
            subprocess.run([sys.executable, str(root/'tools/verify_runtime.py')], cwd=root, env=env, check=True, timeout=40)


if __name__ == '__main__':
    main()
