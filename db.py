import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import JSON, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DATA = ROOT / "var"
DATA.mkdir(exist_ok=True)
engine = create_engine(os.getenv("DATABASE_URL", f"sqlite:///{DATA / 'adrobot.db'}"))


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    token: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    country: Mapped[str]
    offer: Mapped[int]
    settings: Mapped[dict] = mapped_column(JSON)
    campaign_id: Mapped[int | None]
    geo_id: Mapped[int | None]
    offers_id: Mapped[int | None]
    status: Mapped[str]
    error: Mapped[str | None]

    @property
    def alias(self):
        return f"adrobot-{self.token}"


class OfferDraft(Base):
    __tablename__ = "offer_drafts"

    token: Mapped[str] = mapped_column(primary_key=True)
    campaign_id: Mapped[int]
    stream_id: Mapped[int]
    tracker: Mapped[str]
    title: Mapped[str]
    baseline: Mapped[list] = mapped_column(JSON)
    rows: Mapped[list] = mapped_column(JSON)
    catalog: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int]
    published: Mapped[bool]
