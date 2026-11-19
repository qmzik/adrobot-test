from typing import Annotated
from uuid import UUID, uuid4

import pycountry
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from filelock import FileLock
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

import editor
import keitaro as kt
from db import Campaign, OfferDraft, DATA, ROOT, engine

app = FastAPI(title="Adrobot")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
countries = sorted((c.alpha_2, c.name) for c in pycountry.countries)
Text = Annotated[str, Form()]
CAMPAIGN_PREFIX = "test_lebedev_"


def page(request, *, error=None, status=200, **values):
    try:
        options = kt.offers()
        if not options:
            error = error or "В Keitaro нет доступных активных офферов."
    except kt.TrackerError as exc:
        options, error, status = [], str(exc), 503
    context = dict(options=options, countries=countries, token=uuid4().hex, error=error)
    context.update(values)
    return templates.TemplateResponse(request=request, name="form.html", context=context, status_code=status)


@app.get("/")
def form(request: Request):
    return page(request)


def check_origin(request):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Форма должна быть отправлена из приложения.")


@app.post("/campaigns")
def create(request: Request, token: Annotated[UUID, Form()], name: Text = "",
           country: Text = "", offer: Text = ""):
    check_origin(request)
    token = token.hex
    name, country = name.strip(), country.strip().upper()
    suffix = name.removeprefix(CAMPAIGN_PREFIX).strip()
    full_name = CAMPAIGN_PREFIX + suffix
    offer_id = offer.partition(" · ")[0].strip()
    if not (suffix and len(full_name) <= 160 and pycountry.countries.get(alpha_2=country)
            and offer_id.isascii() and offer_id.isdigit() and 0 < len(offer_id) <= 10):
        return page(request, error="Введите название, выберите страну и оффер из списка.",
                    status=422, token=token, name=name, country=country, selected=offer)
    with FileLock(DATA / f"{token}.lock"), Session(engine) as db:
        c = db.get(Campaign, token)
        recovering = c is not None
        if not c:
            c = Campaign(token=token, name=full_name, country=country, offer=int(offer_id),
                         settings=kt.settings(), status="pending")
            db.add(c)
            db.commit()
        elif c.name not in (name, full_name) or (country, int(offer_id)) != (c.country, c.offer):
            raise HTTPException(409, "Заявка уже отправлена с другими параметрами.")
        if c.status != "verified":
            try:
                kt.provision(db, c, recovering)
                c.status, c.error = "verified", None
            except kt.TrackerError as exc:
                c.status, c.error = "error", str(exc)
            db.commit()
    return RedirectResponse(f"/campaigns/{token}", status_code=303)


@app.get("/campaigns/{token}")
def result(request: Request, token: UUID):
    with Session(engine) as db:
        campaign = db.get(Campaign, token.hex)
        if not campaign:
            raise HTTPException(404, "Заявка не найдена.")
        return templates.TemplateResponse(request=request, name="result.html",
                                          context={"c": campaign, "host": kt.host()})


@app.get("/editor")
def select_flow(request: Request, campaign_id: int | None = None):
    flows, error = [], None
    if campaign_id is not None:
        try:
            flows = [s for s in kt.api("GET", f"campaigns/{campaign_id}/streams") if s["schema"] == "landings"]
            if not flows:
                error = "В кампании нет потоков с офферами."
        except kt.TrackerError as exc:
            error = str(exc)
    return templates.TemplateResponse(request=request, name="select_flow.html",
                                      context=dict(campaign_id=campaign_id, flows=flows, error=error))


@app.post("/editor/load")
def open_draft(request: Request, campaign_id: Annotated[int, Form()], stream_id: Annotated[int, Form()]):
    check_origin(request)
    try:
        stream = editor.load_stream(campaign_id, stream_id)
        catalog = {str(o["id"]): o["name"] for o in kt.offers()}
    except (editor.EditError, kt.TrackerError) as exc:
        return templates.TemplateResponse(request=request, name="select_flow.html", status_code=400,
                                          context=dict(campaign_id=campaign_id, flows=[], error=str(exc)))
    baseline = editor.snapshot(stream)
    token = uuid4().hex
    with Session(engine) as db:
        db.add(OfferDraft(token=token, campaign_id=campaign_id, stream_id=stream_id,
                          title=stream["name"], tracker=kt.host(), baseline=baseline,
                          rows=editor.draft_rows(baseline), catalog=catalog, revision=0, published=False))
        db.commit()
    return RedirectResponse(f"/editor/{token}", status_code=303)


def render_draft(request, draft, error=None, status=200):
    used = {str(r["offer_id"]) for r in draft.rows}
    available = {k: v for k, v in draft.catalog.items() if k not in used}
    return templates.TemplateResponse(request=request, name="editor.html", status_code=status,
                                      context=dict(d=draft, available=available, error=error))


def get_draft(db, token):
    draft = db.get(OfferDraft, token.hex)
    if not draft:
        raise HTTPException(404, "Черновик не найден.")
    return draft


@app.get("/editor/{token}")
def view_draft(request: Request, token: UUID):
    with Session(engine) as db:
        return render_draft(request, get_draft(db, token))


@app.post("/editor/{token}")
def update_draft(request: Request, token: UUID, action: Text, revision: Annotated[int, Form()],
                 offer_id: Annotated[int | None, Form()] = None, share: Annotated[int | None, Form()] = None):
    check_origin(request)
    with FileLock(DATA / f"{token.hex}.lock"), Session(engine) as db:
        draft = get_draft(db, token)
        if revision != draft.revision:
            return render_draft(request, draft, "Черновик уже обновлён. Проверьте показанные доли.", 409)
        try:
            if action == "publish":
                if draft.tracker != kt.host():
                    raise editor.EditError("Адрес Keitaro изменился. Загрузите поток заново.")
                with FileLock(DATA / f"stream-{draft.stream_id}.lock"):
                    editor.publish(draft)
            elif action == "cancel":
                draft.rows = editor.draft_rows(draft.baseline)
                draft.published = False
            else:
                editor.edit(draft, action, offer_id, share)
                draft.published = False
        except editor.EditError as exc:
            return render_draft(request, draft, str(exc), 409)
        except kt.TrackerError as exc:
            return render_draft(request, draft, str(exc), 502)
        draft.revision += 1
        db.commit()
    return RedirectResponse(f"/editor/{token.hex}", status_code=303)
