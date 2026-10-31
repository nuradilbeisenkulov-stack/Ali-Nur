"""Reproducible aggregate-only checks; no invented accuracy or pseudo-labels."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter

from scripts.common import InputError, iter_jsonl, resolve_data_dir, validate_result


def inventory(path: Path) -> dict:
    kinds, languages, roles = Counter(), Counter(), Counter()
    present = Counter()
    rows = 0
    keys = ("category", "priority", "reporter_hash", "created_at", "images_count", "reported_nick", "rule_refs_raw")
    for _, row in iter_jsonl(path):
        rows += 1
        kinds[str(row.get("kind", "missing"))] += 1
        languages[str(row.get("lang", "missing"))] += 1
        roles.update(str(m.get("role", "missing")) for m in row.get("messages", []) if isinstance(m, dict))
        for key in keys:
            if row.get(key) not in (None, "", [], {}):
                present[key] += 1
    return {
        "filename": path.name,
        "rows": rows,
        "size_bytes": path.stat().st_size,
        "kinds": dict(sorted(kinds.items())),
        "languages": dict(sorted(languages.items())),
        "message_roles": dict(sorted(roles.items())),
        "nonempty_fields": {key: present[key] for key in keys},
    }


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (position - lo) * (ordered[hi] - ordered[lo])


def evaluate(data_dir: Path, limit: int | None = None) -> dict:
    from app.engine import TriageEngine

    inventory_result = {}
    for name, filename in (("train", "tickets_train.jsonl.gz"), ("valid", "tickets_valid.jsonl")):
        path = data_dir / filename
        inventory_result[name] = inventory(path) if path.exists() else {"missing": True, "filename": filename}
    rules_doc = json.loads((data_dir / "rules.json").read_text(encoding="utf-8"))
    source_rules = [
        (str(section.get("category", "")), str(point["ref"]), str(point["text"]))
        for section in rules_doc["rules"] for point in section.get("points", [])
    ]
    exact_rules = set(source_rules)
    init_start = perf_counter()
    engine = TriageEngine(data_dir)
    init_ms = (perf_counter() - init_start) * 1000
    durations: list[float] = []
    counts = Counter()
    categories, priorities, languages, errors = Counter(), Counter(), Counter(), Counter()
    confidence_total = 0.0
    # This engine has never seen training records: no cross-dataset linkage.
    for index, (_, ticket) in enumerate(iter_jsonl(data_dir / "tickets_valid.jsonl")):
        if limit is not None and index >= limit:
            break
        started = perf_counter()
        result = engine.triage(ticket)
        durations.append((perf_counter() - started) * 1000)
        found = validate_result(result, engine.taxonomy, ticket.get("kind"), exact_rules)
        counts["tickets"] += 1
        counts["ai_generated"] += any(r.startswith("Контекстный черновик") for r in result["reasons"])
        counts["format_valid"] += not found
        counts["needs_human"] += bool(result.get("needs_human"))
        counts["spam_or_duplicate"] += bool(result.get("is_spam_or_duplicate"))
        counts["has_citation"] += bool(result.get("draft_reply", {}).get("cited"))
        counts["citations"] += len(result.get("draft_reply", {}).get("cited", []))
        counts["exact_citations"] += sum(
            (c.get("section"), c.get("ref"), c.get("text")) in exact_rules
            for c in result.get("draft_reply", {}).get("cited", [])
        )
        confidence_total += result.get("confidence", 0)
        categories[result.get("category", "missing")] += 1
        priorities[result.get("priority", "missing")] += 1
        languages[result.get("lang", "missing")] += 1
        errors.update(found)
    n = counts["tickets"]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "local_ai" if engine.ai.enabled else "local_deterministic",
        "ai": engine.ai.status(),
        "inventory": inventory_result,
        "rules": {"sections": len(rules_doc["rules"]), "points": len(source_rules), "unique_ref_strings": len({r[1] for r in source_rules}), "citation_identity": "section + ref + exact text"},
        "taxonomy_version": engine.taxonomy.get("version"),
        "evaluated_split": "valid",
        "limit": limit,
        "checks": {**dict(counts), "errors": dict(errors), "format_valid_rate": counts["format_valid"] / n if n else None, "needs_human_rate": counts["needs_human"] / n if n else None, "mean_confidence": confidence_total / n if n else None},
        "predicted_categories": dict(sorted(categories.items())),
        "predicted_priorities": dict(sorted(priorities.items())),
        "predicted_languages": dict(sorted(languages.items())),
        "latency_ms": {"engine_init": round(init_ms, 3), "p50": round(percentile(durations, .50), 3), "p95": round(percentile(durations, .95), 3), "mean": round(statistics.mean(durations), 3) if durations else 0.0, "total_inference": round(sum(durations), 3)},
        "latency_method": "perf_counter around sequential engine.triage calls; excludes JSONL I/O, inventory, initialization, HTTP and UI; includes dedup; no concurrency",
        "environment": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine()},
        "cost_per_ticket": {"external_api_usd": 0.0, "hardware": "Local CPU, memory, storage and electricity are not zero-cost; not monetized in this report."},
        "quality_metrics": {"accuracy": None, "macro_f1": None, "reason": "No nonempty category/priority gold labels in the supplied train and valid splits. Requires independently human-labeled held-out data. No pseudo-label comparison is treated as validation."},
        "limitations": ["Structural correctness and existence of a source rule do not establish semantic relevance or correct classification.", "Confidence is a heuristic score, not a calibrated probability.", "Language and retrieval quality require human assessment, especially kk, uz, lat and und.", "Attachments are counted, never visually interpreted.", "Training tickets and administrator outcomes are not used as model input or labels.", "Runtime deduplication is sequential and bounded; rate depends on file order and retained local state."],
    }


def as_markdown(report: dict) -> str:
    checks = report["checks"]
    n = checks["tickets"]
    lines = ["# Support Copilot — воспроизводимые проверки", "", f"Дата UTC: {report['generated_at_utc']}. Режим: {report['mode']}.", "", "## Инвентаризация", "", "| Набор | Записей | complaint | report | Непустая category | Непустой priority |", "|---|---:|---:|---:|---:|---:|"]
    for name, info in report["inventory"].items():
        if info.get("missing"):
            lines.append(f"| {name} | файл отсутствует | — | — | — | — |")
        else:
            lines.append(f"| {name} | {info['rows']:,} | {info['kinds'].get('complaint', 0):,} | {info['kinds'].get('report', 0):,} | {info['nonempty_fields']['category']} | {info['nonempty_fields']['priority']} |")
    lines += ["", "Языки по исходному полю `lang`:", "", "| Язык | train | valid |", "|---|---:|---:|"]
    langs = sorted({lang for info in report["inventory"].values() for lang in info.get("languages", {})})
    for lang in langs:
        lines.append(f"| {lang} | {report['inventory']['train'].get('languages', {}).get(lang, 0):,} | {report['inventory']['valid'].get('languages', {}).get(lang, 0):,} |")
    rules = report["rules"]
    lines += ["", f"Правила: {rules['sections']} разделов, {rules['points']} пунктов, {rules['unique_ref_strings']} уникальный номер. Номера повторяются в разных разделах; проверяется сочетание `section + ref + точный текст`.", "", f"## Техническая проверка {n:,} обращений valid", "", "| Проверка | Результат |", "|---|---:|", f"| Формат, категория по kind, приоритет, целостность ссылок | {checks['format_valid']:,} / {n:,} |", f"| Передано человеку | {checks['needs_human']:,} / {n:,} ({(checks['needs_human_rate'] or 0):.1%}) |", f"| Обращения с цитатами | {checks['has_citation']:,} |", f"| Цитаты, точно существующие в исходных points | {checks['exact_citations']:,} / {checks['citations']:,} |", f"| Флаг спама / дубля | {checks['spam_or_duplicate']:,} |", f"| p50, мс | {report['latency_ms']['p50']} |", f"| p95, мс | {report['latency_ms']['p95']} |", f"| Инициализация, мс | {report['latency_ms']['engine_init']} |", "| Внешний API, USD / обращение | 0 |", "", "Задержки измерены `perf_counter` вокруг последовательных вызовов `engine.triage`: без чтения JSONL, инвентаризации, инициализации, HTTP и интерфейса; с дедупликацией. Это замер на текущей машине, а не гарантия производительности под нагрузкой. Локальное вычислительное оборудование, память, хранение и электричество требуют ресурсов; их денежная стоимость не оценивалась.", "", "Окружение: " + ", ".join(f"{key}={value}" for key, value in report["environment"].items()) + ".", "", "## Что этот отчёт не измеряет", "", "В обоих наборах отсутствуют непустые эталонные `category` и `priority`. Поэтому accuracy и macro-F1 **не вычислялись**. Сравнение с псевдометками не является валидацией. Нужна независимая ручная разметка отложенной выборки; пустой шаблон: `outputs/manual_evaluation.csv`.", "", "Корректный формат и существующая цитата не доказывают правильность категории, приоритета или смысловую релевантность правила. Confidence — эвристический показатель, не калиброванная вероятность. Язык и шаблоны, особенно kk/uz/lat/und, требуют ручной проверки. Содержимое вложений недоступно. Ответы администратора и поля результата рассмотрения не используются ни как признаки, ни как обучающие метки. Оценка доли дублей зависит от порядка записей и ограниченного состояния внутри одного запуска.", "", "## Распределение прогнозов", "", "| Категория | Количество |", "|---|---:|"]
    lines.extend(f"| {key} | {value:,} |" for key, value in report["predicted_categories"].items())
    lines += ["", "| Приоритет | Количество |", "|---|---:|"]
    lines.extend(f"| {key} | {value:,} |" for key, value in report["predicted_priorities"].items())
    lines += ["", "## Воспроизведение", "", "```sh", "SUPPORT_AI=off make evaluate", "```", "", "Полный машиночитаемый отчёт: `outputs/evaluation.json`. Файлы отчёта содержат только агрегаты; тексты обращений и идентификаторы в них не сохраняются.", ""]
    if checks["errors"]:
        lines += ["Технические ошибки: `" + json.dumps(checks["errors"], ensure_ascii=False) + "`.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--limit", type=int, help="Optional maximum valid records (inventory remains complete)")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    try:
        report = evaluate(resolve_data_dir(args.data_dir), args.limit)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output_dir / "evaluation.md").write_text(as_markdown(report), encoding="utf-8")
        print(f"Проверено {report['checks']['tickets']} обращений. Ошибки формата: {sum(report['checks']['errors'].values())}.")
        return 1 if report["checks"]["errors"] else 0
    except (InputError, OSError, ValueError) as exc:
        print(str(exc) if isinstance(exc, InputError) else f"Ошибка оценки: {type(exc).__name__}. Проверьте локальные данные.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
