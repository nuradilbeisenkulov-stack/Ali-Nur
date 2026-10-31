"""Configuration without importing or copying private case data."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def setting(key: str, default: str) -> str:
    if key in os.environ:
        return os.environ[key]
    env_file = ROOT / '.env'
    if env_file.is_file():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                name, value = line.split('=', 1)
                if name.strip() == key:
                    return value.strip().strip('\"\'')
    return default


def get_data_dir() -> Path:
    path = Path(setting('SUPPORT_DATA_DIR', 'demo_data')).expanduser()
    return path if path.is_absolute() else ROOT / path


def get_db_path() -> Path:
    path = Path(setting('SUPPORT_DB_PATH', 'work/state/copilot.sqlite3')).expanduser()
    return path if path.is_absolute() else ROOT / path

