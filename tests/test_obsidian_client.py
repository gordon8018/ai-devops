import pytest
from unittest.mock import patch, MagicMock


def _make_client():
    import importlib, sys
    if "orchestrator.bin.obsidian_client" in sys.modules:
        del sys.modules["orchestrator.bin.obsidian_client"]
    import orchestrator.bin.obsidian_client as m
    return m.ObsidianClient(base_url="http://localhost:27123", token="test-token")


def test_search_returns_results():
    client = _make_client()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "results": [
            {"filename": "notes/meeting.md", "matches": [{"context": "discussed auth bug"}]}
        ]
    }
    with patch("requests.post", return_value=fake_response):
        results = client.search("auth bug", limit=3)
    assert len(results) == 1
    assert results[0]["path"] == "notes/meeting.md"
    assert "auth bug" in results[0]["excerpt"]


def test_search_returns_empty_on_connection_error():
    client = _make_client()
    with patch("requests.post", side_effect=Exception("refused")):
        results = client.search("anything")
    assert results == []


def test_search_returns_empty_on_4xx():
    client = _make_client()
    fake_response = MagicMock()
    fake_response.status_code = 401
    with patch("requests.post", return_value=fake_response):
        results = client.search("anything")
    assert results == []


def test_get_note_returns_content():
    client = _make_client()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = "# Meeting Notes\nDiscussed auth bug fix."
    with patch("requests.get", return_value=fake_response):
        content = client.get_note("notes/meeting.md")
    assert "auth bug" in content


def test_get_note_returns_empty_on_error():
    client = _make_client()
    with patch("requests.get", side_effect=Exception("timeout")):
        content = client.get_note("notes/missing.md")
    assert content == ""


def test_from_env(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_API_TOKEN", "my-token")
    monkeypatch.setenv("OBSIDIAN_API_PORT", "27123")
    import importlib, sys
    if "orchestrator.bin.obsidian_client" in sys.modules:
        del sys.modules["orchestrator.bin.obsidian_client"]
    import orchestrator.bin.obsidian_client as m
    importlib.reload(m)
    client = m.ObsidianClient.from_env()
    assert client.token == "my-token"
    assert "27123" in client.base_url
