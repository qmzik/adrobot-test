"""Локальный тестовый Admin API. Начальное состояние восстанавливается при запуске."""
from copy import deepcopy

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_id: int
    state: str
    share: int = Field(ge=0, le=100)


class Update(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offers: list[Target]


def create_api():
    app = FastAPI(title="Тестовый Keitaro")
    catalog = [{"id": 41, "name": "Первый оффер", "state": "active"},
               {"id": 42, "name": "Второй оффер", "state": "active"}]
    flows = {
        10: dict(id=10, campaign_id=1, name="Google", schema="redirect", filters=[{"name": "country"}]),
        11: dict(id=11, campaign_id=1, name="Тестовый поток", schema="landings", filters=[], landings=[],
                 offers=[dict(offer_id=41, state="active", share=100)]),
    }
    prefix = "/admin_api/v1"

    @app.get(prefix + "/offers")
    def offers():
        return catalog

    @app.get(prefix + "/campaigns/{campaign_id}/streams")
    def streams(campaign_id: int):
        if campaign_id != 1:
            raise HTTPException(404)
        return list(flows.values())

    @app.get(prefix + "/streams/{stream_id}")
    def stream(stream_id: int):
        if stream_id not in flows:
            raise HTTPException(404)
        return deepcopy(flows[stream_id])

    @app.put(prefix + "/streams/{stream_id}")
    def update(stream_id: int, data: Update):
        if stream_id != 11:
            raise HTTPException(404)
        ids = [t.offer_id for t in data.offers]
        if (not set(ids).issubset({41, 42}) or len(set(ids)) != len(ids)
                or sum(t.share for t in data.offers if t.state == "active") != 100):
            raise HTTPException(422, "Некорректный состав потока")
        flows[stream_id]["offers"] = [target.model_dump() for target in data.offers]
        return stream(stream_id)

    return app


app = create_api()
