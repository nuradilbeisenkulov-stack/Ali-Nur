"""HTTP integration with an isolated temporary database and synthetic tickets."""
import importlib

from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client(monkeypatch, tmp_path, data_dir):
    monkeypatch.setenv("SUPPORT_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(data_dir))
    import app.main
    module = importlib.reload(app.main)
    with TestClient(module.app) as test_client:
        yield test_client


def test_service_health_and_contract(client):
    assert client.get("/health").status_code == 200
    response = client.post("/triage", json={"kind": "report", "messages": [{"role": "player", "text": "Подскажите адрес автошколы в игре."}]})
    assert response.status_code == 200
    result = response.json()
    assert result["category"].startswith("report.")
    assert result["priority"] in {"p0", "p1", "p2", "p3"}
    assert "draft_reply" in result
    assert "ticket_id" not in result


def test_bad_request_has_validation_error(client):
    assert client.post("/triage", json={"kind": "unknown", "messages": []}).status_code == 422
    assert client.post("/triage", json={"kind": "report"}).status_code == 422


def test_queue_edits_survive_readback_and_send_is_local(client):
    payload = {"kind": "report", "lang": "ru", "messages": [{"role": "player", "text": "Синтетический персонаж не может выйти из здания."}]}
    created = client.post("/api/tickets", json=payload)
    assert created.status_code in {200, 201}
    item = created.json()
    ticket_id = item["id"]
    text = "Синтетическая правка администратора: обращение передано на рассмотрение."
    edit = client.patch(f"/api/tickets/{ticket_id}", json={"action": "edit", "draft_text": text})
    assert edit.status_code == 200
    assert edit.json()["draft_text"] == text
    rows = client.get("/api/tickets").json()
    assert next(row for row in rows if row["id"] == ticket_id)["draft_text"] == text
    send = client.patch(f"/api/tickets/{ticket_id}", json={"action": "send"})
    assert send.status_code == 200
    assert send.json()["status"] != item["status"]
    assert send.json()["draft_text"] == text


def test_queue_can_escalate_and_unknown_items_are_404(client):
    payload = {"kind": "report", "messages": [{"role": "player", "text": "Нужна помощь с синтетическим обращением."}]}
    item = client.post("/api/tickets", json=payload).json()
    escalated = client.patch(f"/api/tickets/{item['id']}", json={"action": "escalate"})
    assert escalated.status_code == 200
    assert escalated.json()["status"] != item["status"]
    assert escalated.json()["result"]["needs_human"] is True
    assert client.patch("/api/tickets/not-a-real-id", json={"action": "send"}).status_code == 404
