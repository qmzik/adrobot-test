import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import editor
import main
from db import Base
from tests.demo_api import create_api


@pytest.fixture
def clients(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'editor.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "DATA", tmp_path)
    monkeypatch.setenv("KEITARO_API_KEY", "test")
    monkeypatch.setenv("KEITARO_URL", "http://testserver")
    remote = TestClient(create_api())
    monkeypatch.setattr(main.kt.httpx, "request", remote.request)
    return TestClient(main.app), remote


def open_stream(client):
    result = client.post("/editor/load", data=dict(campaign_id=1, stream_id=11))
    assert result.status_code == 200
    return result.url.path


def act(client, url, action, **fields):
    html = client.get(url).text
    version = re.search(r'name="revision" value="(\d+)"', html)[1]
    return client.post(url, data=dict(revision=version, action=action, **fields))


def test_publish_50_50_and_verify_over_api(clients):
    web, api = clients
    assert 'value="11"' in web.get("/editor?campaign_id=1").text
    assert 'value="10"' not in web.get("/editor?campaign_id=1").text
    url = open_stream(web)
    path = "/admin_api/v1/streams/11"
    before = api.get(path).json()
    assert act(web, url, "add", offer_id=42).text.count("50%") == 2
    assert api.get(path).json() == before
    assert "Опубликовано." in act(web, url, "publish").text
    expected = [dict(offer_id=i, state="active", share=50) for i in (41, 42)]
    assert api.get(path).json() == dict(before, offers=expected)
    assert web.get(open_stream(web)).text.count("50%") == 2
    assert "Помечен к удалению" in act(web, url, "remove", offer_id=41).text
    assert act(web, url, "restore", offer_id=41).text.count("50%") == 2
    act(web, url, "remove", offer_id=41)
    assert act(web, url, "cancel").text.count("50%") == 2
    act(web, url, "remove", offer_id=41)
    act(web, url, "publish")
    assert api.get(path).json()["offers"] == [dict(offer_id=42, share=100, state="active")]
    assert len(api.get("/admin_api/v1/offers").json()) == 2


def test_foreign_changes_and_stale_form(clients):
    web, api = clients
    url = open_stream(web)
    assert act(web, url, "remove", offer_id=41).status_code == 409
    act(web, url, "add", offer_id=42)
    assert web.post(url, data=dict(revision=0, action="cancel")).status_code == 409
    remote = [dict(offer_id=42, state="active", share=100)]
    api.put("/admin_api/v1/streams/11", json=dict(offers=remote)).raise_for_status()
    assert act(web, url, "publish").status_code == 409
    assert api.get("/admin_api/v1/streams/11").json()["offers"] == remote


def test_pin_and_rounding():
    draft = SimpleNamespace(rows=editor.draft_rows(
        [dict(offer_id=i, share=25, state="active") for i in range(4)]))
    editor.edit(draft, "pin", 0, 25)
    editor.edit(draft, "remove", 3, None)
    assert [r["share"] for r in editor.payload(draft.rows)] == [25, 38, 37]
    editor.edit(draft, "restore", 3, None)
    assert [r["share"] for r in editor.payload(draft.rows)] == [25] * 4
