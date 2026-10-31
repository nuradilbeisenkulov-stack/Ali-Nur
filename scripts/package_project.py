"""Build a GitHub-ready source ZIP using a strict public-file allowlist."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [ROOT / name for name in (
        'README.md', 'Makefile', 'requirements.txt', 'requirements.lock',
        '.env.example', '.gitignore', '.dockerignore', 'Dockerfile', 'compose.yaml', 'pytest.ini',
    )]
    allowed = {'.py', '.html', '.css', '.js', '.json', '.md', '.yml', '.yaml'}
    for directory in ('app', 'scripts', 'tests', 'demo_data', 'docs', '.github'):
        files.extend(path for path in (ROOT / directory).rglob('*')
                     if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts
                     and path.suffix in allowed)
    target = ROOT / 'outputs' / 'support-copilot-github-ready.zip'
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, 'support-copilot/' + path.relative_to(ROOT).as_posix())
    print(f'Public source archive: {target.name}; {len(files)} files')


if __name__ == '__main__':
    main()
