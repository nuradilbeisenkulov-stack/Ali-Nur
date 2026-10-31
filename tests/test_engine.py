"""Behavioral regression tests. All examples are synthetic, never dataset excerpts."""
import copy
import json

import pytest

from app.engine import TriageEngine
from scripts.common import validate_result


def test_contract_and_taxonomy_membership(engine, data_dir, make_ticket):
    source = json.loads((data_dir / "rules.json").read_text())
    citations = {(s["category"], p["ref"], p["text"]) for s in source["rules"] for p in s.get("points", [])}
    for kind in ("report", "complaint"):
        ticket = make_ticket("Игрок Example_Nick оскорбляет моего персонажа в чате.", kind=kind)
        result = engine.triage(ticket)
        assert not validate_result(result, engine.taxonomy, kind, citations)
        assert result["extracted"]["server"] is None


def test_admin_and_outcome_fields_do_not_change_prediction(data_dir, make_ticket):
    ticket = make_ticket("Не понимаю, где можно получить водительскую лицензию.")
    clean = TriageEngine(data_dir).triage(ticket)
    poisoned = copy.deepcopy(ticket)
    poisoned["messages"].append({"role": "admin", "text": "ВЗЛОМ АККАУНТА. Игрок наказан за читы 5.2. Оплата не дошла.", "attachments": ["private-screenshot"]})
    poisoned.update(verdict="approved", punishment="навсегда", violation="5.2", category="report.payment", priority="p0", status=2)
    assert TriageEngine(data_dir).triage(poisoned) == clean


def test_original_payload_is_not_mutated(engine, make_ticket):
    ticket = make_ticket("Маған кјмектесіңіз, кейіпкерім кептеліп ќалды.", lang="kk")
    original = copy.deepcopy(ticket)
    engine.triage(ticket)
    assert ticket == original


@pytest.mark.parametrize("overrides,expected", [({}, False), ({"images_count": 0}, False), ({"images_count": 2}, True), ({"messages": [{"role": "player", "text": "Есть фото", "attachments": []}]}, False), ({"messages": [{"role": "player", "text": "Материал", "attachments": [{"name": "synthetic.png"}]}]}, True)])
def test_evidence_requires_attachment_metadata(engine, make_ticket, overrides, expected):
    result = engine.triage(make_ticket("Скриншоты всё доказывают, видео у меня есть.", **overrides))
    assert result["extracted"]["has_evidence"] is expected


def test_nonexistent_reference_is_never_invented(engine, make_ticket):
    result = engine.triage(make_ticket("Где найти автошколу для сдачи экзамена?", rule_refs_raw="9999.8888"))
    assert "9999.8888" not in result["extracted"]["rule_refs"]
    assert all(c["ref"] != "9999.8888" for c in result["draft_reply"]["cited"])
    assert result["reasons"]


def test_unrelated_real_reference_is_not_a_citation(engine, make_ticket):
    result = engine.triage(make_ticket("Как получить водительскую лицензию?", rule_refs_raw="5.2"))
    assert result["draft_reply"]["cited"] == []
    assert result["extracted"]["rule_refs"] == []


@pytest.mark.parametrize("text,kind", [
    ("Донат оплачен, но валюта на баланс ещё не зачислена.", "report"),
    ("Прошу вернуть денежный платёж за покупку.", "report"),
    ("Мой аккаунт взломали, больше не могу войти.", "report"),
    ("Прошу снять блокировку с моего аккаунта.", "report"),
    ("Хочу обжаловать бан моего персонажа.", "complaint"),
    ("Администратор несправедливо заблокировал персонажа.", "complaint"),
    ("Накажите игрока Example_Nick за оскорбления.", "complaint"),
    ("Please refund my payment.", "report"),
])
def test_sensitive_requests_always_require_human(engine, make_ticket, text, kind):
    result = engine.triage(make_ticket(text, kind=kind))
    assert result["needs_human"] is True
    draft = result["draft_reply"]["text"].lower()
    for promise in ("будет наказан", "будет заблокирован", "вернём деньги", "разбаним", "нарушение подтверждено", "you will be refunded"):
        assert promise not in draft


@pytest.mark.parametrize("lang,text", [
    ("ru", "Мне нужна помощь, персонаж застрял в гараже."),
    ("kk", "Көмектесіңізші, кейіпкерім гаражда тұрып қалды."),
    ("uz", "Yordam bering, qahramonim garajdan chiqa olmayapti."),
    ("en", "Please help me, my character is stuck in a garage."),
    ("es", "Por favor, mi personaje está atascado en el garaje."),
    ("pt", "Por favor, meu personagem está preso na garagem."),
])
def test_declared_supported_languages(engine, make_ticket, lang, text):
    result = engine.triage(make_ticket(text, lang=lang))
    assert result["lang"] == lang
    assert result["draft_reply"]["lang"] == lang
    assert result["draft_reply"]["text"]


@pytest.mark.parametrize("lang", [None, "und", "lat"])
def test_one_latin_word_does_not_guess_a_language(engine, make_ticket, lang):
    ticket = make_ticket("xyzabc", lang=lang)
    result = engine.triage(ticket)
    assert result["lang"] in {"lat", "und"}
    assert result["needs_human"] is True


def test_reported_nickname_wins_over_other_text(engine, make_ticket):
    result = engine.triage(make_ticket("Игрок Another_Name толкнул персонажа.", kind="complaint", reported_nick="Target_Example"))
    assert result["extracted"]["nickname"] == "Target_Example"


def test_duplicate_needs_same_reporter_and_one_hour(engine, make_ticket):
    base = make_ticket("Персонаж намертво застрял в гараже, выйти невозможно.", reporter_hash="synthetic-a", created_at="2026-10-01T10:00:00Z")
    assert engine.triage(base)["is_spam_or_duplicate"] is False
    duplicate = {**base, "created_at": "2026-10-01T10:59:59Z"}
    assert engine.triage(duplicate)["is_spam_or_duplicate"] is True
    different = {**base, "reporter_hash": "synthetic-b", "created_at": "2026-10-01T10:30:00Z"}
    assert engine.triage(different)["is_spam_or_duplicate"] is False
    late = {**base, "created_at": "2026-10-01T13:00:00Z"}
    assert engine.triage(late)["is_spam_or_duplicate"] is False


@pytest.mark.parametrize("missing", ["reporter_hash", "created_at"])
def test_missing_identity_or_time_does_not_declare_duplicate(engine, make_ticket, missing):
    ticket = make_ticket("Не получается вывести персонажа из гаража.", reporter_hash="synthetic-a", created_at="2026-10-01T10:00:00")
    ticket.pop(missing)
    assert engine.triage(ticket)["is_spam_or_duplicate"] is False
    assert engine.triage(ticket)["is_spam_or_duplicate"] is False


def test_duplicate_does_not_link_different_problems(engine, make_ticket):
    engine.triage(make_ticket("Мой персонаж застрял в гараже.", reporter_hash="synthetic-a", created_at="2026-10-01T10:00:00Z"))
    result = engine.triage(make_ticket("Купил валюту, платёж прошёл, деньги не зачислены.", reporter_hash="synthetic-a", created_at="2026-10-01T10:05:00Z"))
    assert result["is_spam_or_duplicate"] is False


def test_kazakh_lookalike_normalization_preserves_prediction(data_dir, make_ticket):
    text = "маған көмек керек, кейіпкерім қақпа алдында тұрып қалды."
    substituted = text.translate(str.maketrans("қғңәөұү", "ќґѕєјўї"))
    normal = TriageEngine(data_dir).triage(make_ticket(text, lang="kk"))
    noisy = TriageEngine(data_dir).triage(make_ticket(substituted, lang="kk"))
    assert normal == noisy


def test_removed_taxonomy_category_is_never_emitted(tmp_path, data_dir, make_ticket):
    taxonomy = json.loads((data_dir / "taxonomy.json").read_text())
    taxonomy["categories"] = [c for c in taxonomy["categories"] if c["code"] != "report.help"]
    (tmp_path / "taxonomy.json").write_text(json.dumps(taxonomy, ensure_ascii=False))
    (tmp_path / "rules.json").write_bytes((data_dir / "rules.json").read_bytes())
    result = TriageEngine(tmp_path).triage(make_ticket("Персонаж застрял в текстурах, нужна помощь с телепортом."))
    allowed = {c["code"] for c in taxonomy["categories"] if c["kind"] == "report"}
    assert result["category"] in allowed
    assert result["category"] != "report.help"
