"""Stream JSONL tickets to predictions without using labels or external APIs."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from scripts.common import InputError, iter_jsonl, resolve_data_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSONL or JSONL.GZ input")
    parser.add_argument("--output", required=True, type=Path, help="Local JSONL output")
    parser.add_argument("--data-dir", help="Directory containing taxonomy.json and rules.json")
    args = parser.parse_args()
    from app.engine import TriageEngine

    temporary: Path | None = None
    try:
        engine = TriageEngine(resolve_data_dir(args.data_dir))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, prefix=".predict-", suffix=".tmp", delete=False) as target:
            temporary = Path(target.name)
            # Private prediction artifacts are readable only by their owner.
            os.chmod(temporary, 0o600)
            count = 0
            for line_number, ticket in iter_jsonl(args.input):
                try:
                    result = engine.triage(ticket)
                except (ValueError, TypeError, KeyError) as exc:
                    raise InputError(f"Некорректная схема обращения в строке {line_number}.") from exc
                if "ticket_id" in ticket:
                    result = {"ticket_id": ticket["ticket_id"], **result}
                target.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
                count += 1
        os.replace(temporary, args.output)
        temporary = None
        print(f"Готово: {count} обращений. Результат сохранён локально.")
        return 0
    except (InputError, OSError, ValueError) as exc:
        if isinstance(exc, InputError):
            print(str(exc), file=sys.stderr)
        else:
            print(f"Не удалось выполнить прогноз: {type(exc).__name__}. Проверьте файлы данных и пути.", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
