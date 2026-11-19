import os

import httpx


class TrackerError(Exception):
    pass


def host():
    return os.getenv("KEITARO_URL", "https://tlgk.host").rstrip("/")


def settings():
    return {
        "domain_id": int(os.getenv("KEITARO_DOMAIN_ID", "1813")),
        "group_id": int(os.getenv("KEITARO_GROUP_ID", "9799")),
        "traffic_source_id": int(os.getenv("KEITARO_SOURCE_ID", "836")),
    }


def api(method, path, body=None):
    key = os.getenv("KEITARO_API_KEY")
    if not key:
        raise TrackerError("Укажите KEITARO_API_KEY в файле .env.")
    try:
        response = httpx.request(method, f"{host()}/admin_api/v1/{path}",
                                 headers={"Api-Key": key}, json=body, timeout=20)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise TrackerError(f"Keitaro отклонил {method} {path} (HTTP {exc.response.status_code}).") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise TrackerError(f"Не удалось получить ответ Keitaro для {method} {path}.") from exc


def offers():
    return [row for row in api("GET", "offers") if row["state"] == "active"]


def streams(c):
    return api("GET", f"campaigns/{c.campaign_id}/streams")


def flow_specs(c):
    return [
        ("geo_id", dict(name="Country to Google", position=1, type="regular", schema="redirect",
                        action_payload="https://www.google.com/",
                        filters=[dict(name="country", mode="accept", payload=[c.country])])),
        ("offers_id", dict(name="Offers", position=2, type="default", schema="landings",
                           offers=[dict(offer_id=c.offer, state="active", share=100)])),
    ]


def verify(c):
    remote = api("GET", f"campaigns/{c.campaign_id}")
    expected = dict(**c.settings, alias=c.alias, name=c.name, type="position")
    if any(remote.get(k) != v for k, v in expected.items()):
        raise TrackerError("Сохранённые параметры кампании отличаются от заявки.")
    rows = sorted(streams(c), key=lambda s: s["position"])
    if len(rows) != 2:
        raise TrackerError("В кампании должно быть ровно два потока.")
    for (field, spec), row in zip(flow_specs(c), rows):
        for key in ("type", "schema", "position"):
            if row.get(key) != spec[key]:
                raise TrackerError("Порядок или тип потоков отличается от заявки.")
        if row["id"] != getattr(c, field) or row["state"] != "active" or row["action_type"] != "http":
            raise TrackerError("ID, действие или статус потока отличается от заявки.")
    geo, fallback = rows
    filters = [{k: f.get(k) for k in ("name", "mode", "payload")} for f in geo["filters"]]
    targets = [{k: o.get(k) for k in ("offer_id", "state", "share")} for o in fallback["offers"]]
    specs = flow_specs(c)
    if (geo["action_payload"] != specs[0][1]["action_payload"] or filters != specs[0][1]["filters"]
            or fallback["filters"] or fallback["landings"] or targets != specs[1][1]["offers"]):
        raise TrackerError("Адрес, фильтры или доля оффера отличаются от заявки.")


def provision(db, c, recovering):
    if not c.campaign_id:
        if recovering:
            existing = next((r for r in api("GET", "campaigns") if r["alias"] == c.alias), None)
        else:
            existing = None
        if not existing:
            if not any(row["id"] == c.offer for row in offers()):
                raise TrackerError("Выбранный оффер недоступен. Откройте форму и выберите активный оффер.")
            existing = api("POST", "campaigns", dict(**c.settings, name=c.name, alias=c.alias,
                                                      type="position", cost_currency="USD"))
        c.campaign_id = existing["id"]
        db.commit()
    current = streams(c)
    for field, spec in flow_specs(c):
        if getattr(c, field):
            continue
        row = next((s for s in current if s["position"] == spec["position"]), None)
        if row and row["name"] != spec["name"]:
            raise TrackerError("Позицию занимает другой поток. Проверьте кампанию в Keitaro.")
        if not row:
            row = api("POST", "streams", dict(**spec, campaign_id=c.campaign_id, action_type="http"))
        setattr(c, field, row["id"])
        db.commit()
    verify(c)
