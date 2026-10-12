"""Identify the actual loaded application independently of an uncommitted tree."""
import hashlib
from pathlib import Path
import platform
import subprocess
import sonar_activaciones


def identity():
    package = Path(sonar_activaciones.__file__).resolve().parent
    files = {str(p.relative_to(package)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(package.rglob('*.py'))}
    digest = hashlib.sha256('\n'.join(f'{name}:{value}' for name, value in files.items()).encode()).hexdigest()
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True)
    return {'application_sha256': digest, 'application_files': files, 'git_head': result.stdout.strip(),
            'version': sonar_activaciones.__version__, 'python': platform.python_version(),
            'platform': platform.platform(), 'synthetic': True}
