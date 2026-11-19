import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import main
import keitaro as kt
from db import Base


@pytest.fixture
def site(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "DATA", tmp_path)
    remote = {"campaigns": [], "streams": [], "offers": [{"id": 41, "name": "Demo", "state": "active"}]}

    def api(method, path, body=None):
        if method == "POST":
            rows = remote[path]
            row = dict(filters=[], offers=[], landings=[], state="active", **{})
            row.update(body, id=len(rows) + 1)
            rows.append(row)
            if remote.pop("lose_stream_response", False) and path == "streams":
                raise kt.TrackerError("Соединение прервано.")
            return row
        if path.endswith("/streams"):
            return remote["streams"]
        if path.startswith("campaigns/"):
            return remote["campaigns"][0]
        return remote[path]

    monkeypatch.setattr(kt, "api", api)
    client = TestClient(main.app)
    html = client.get("/").text
    token = re.search(r'name="token" value="([^"]+)"', html)[1]
    return client, remote, dict(token=token, name="April", country="au", offer="41 · Demo")


def test_create_and_resubmit(site):
    client, remote, data = site
    for _ in range(2):
        result = client.post("/campaigns", data=data)
        assert result.status_code == 200
        assert "Настройки подтверждены" in result.text
    assert len(remote["campaigns"]) == 1
    geo, fallback = remote["streams"]
    assert geo["filters"] == [dict(name="country", mode="accept", payload=["AU"])]
    assert geo["action_payload"] == "https://www.google.com/"
    assert fallback["offers"] == [dict(offer_id=41, share=100, state="active")]


def test_reconcile_after_lost_response(site, monkeypatch):
    client, remote, data = site
    original = kt.api

    def fail_once(method, path, body=None):
        if method == "POST" and path == "streams" and not remote["streams"]:
            remote["lose_stream_response"] = True
        return original(method, path, body)

    monkeypatch.setattr(kt, "api", fail_once)
    assert "Создание не завершено" in client.post("/campaigns", data=data).text
    assert len(remote["streams"]) == 1
    assert "Настройки подтверждены" in client.post("/campaigns", data=data).text
    assert len(remote["campaigns"]) == 1
    assert len(remote["streams"]) == 2


def test_remote_mismatch(site, monkeypatch):
    client, remote, data = site
    original = kt.api

    def corrupt_share(method, path, body=None):
        result = original(method, path, body)
        if method == "GET" and path.endswith("/streams") and len(result) == 2:
            result[1]["offers"][0]["share"] = 50
        return result

    monkeypatch.setattr(kt, "api", corrupt_share)
    assert "доля оффера отличаются" in client.post("/campaigns", data=data).text


def test_missing_offer_and_invalid_country(site):
    client, remote, data = site
    assert client.post("/campaigns", data=dict(data, country="XX")).status_code == 422
    remote["offers"].clear()
    assert "нет доступных" in client.get("/").text
    assert "Выбранный оффер недоступен" in client.post("/campaigns", data=data).text
    assert not remote["campaigns"]
