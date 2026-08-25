from pathlib import Path
import re
from datetime import datetime as dt, timedelta
from sqlalchemy import Boolean, CheckConstraint, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy import DateTime
from config import settings


db_dir = Path(settings.CHROMA_PATH)
db_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{db_dir / 'app.sqlite3'}",
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class TgUser(Base):
    __tablename__ = "tg_users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    tgid: Mapped[str] = mapped_column(
        String(10),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    status: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    __table_args__ = (
        CheckConstraint(
            "length(tgid) BETWEEN 1 AND 10 "
            "AND tgid NOT GLOB '*[^0-9]*'",
            name="tgid_digits_max_10",
        ),
    )


class IdiomsHistory(Base):
    __tablename__ = "idioms_history"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    datetime: Mapped[dt] = mapped_column(
        DateTime,
        nullable=False,
        default=dt.now,
    )
    text: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )


class Db:
    @staticmethod
    def init_db() -> None:
        Base.metadata.create_all(engine)

    @staticmethod
    def create_user(tgid: int | str, name: str, status: bool = False) -> TgUser:
        tgid_str = str(tgid)

        if not re.fullmatch(r"\d{1,10}", tgid_str):
            raise ValueError("tgid должен содержать от 1 до 10 цифр")

        with SessionLocal() as session:
            user = session.scalar(
                select(TgUser).where(TgUser.tgid == tgid_str)
            )

            if user is not None:
                user.name = name
                user.status = status
                session.commit()
                session.refresh(user)
                return user

            user = TgUser(
                tgid=tgid_str,
                name=name,
                status=status,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    @staticmethod
    def get_users_tg_ids() -> list[TgUser]:
        with SessionLocal() as session:
            result_raw = list(
                session.scalars(
                    select(TgUser).where(TgUser.status == True).order_by(TgUser.id)
                ).all())
            result = [row.tgid for row in result_raw]
            return result

    @staticmethod
    def update_user_status(tgid: int | str, status: bool) -> bool:
        with SessionLocal() as session:
            user = session.scalar(
                select(TgUser).where(TgUser.tgid == str(tgid))
            )

            if user is None:
                return False

            user.status = status
            session.commit()
            return True

    @staticmethod
    def add_idiom(idiom_id: int, text: str) -> IdiomsHistory:
        with SessionLocal() as session:
            daily_text = IdiomsHistory(
                id=idiom_id,
                text=text,
            )
            session.add(daily_text)
            session.commit()
            session.refresh(daily_text)
            return daily_text

    @staticmethod
    def get_today_idiom() -> str | None:
        with SessionLocal() as session:
            daily_text = session.scalar(
                select(IdiomsHistory)
                .order_by(IdiomsHistory.datetime.desc())
            )

            return daily_text.text if daily_text else None

    @staticmethod
    def get_idioms_ids():
        with SessionLocal() as session:
            result_raw = list(
                session.scalars(
                    select(IdiomsHistory)
                ).all())
            if not result_raw:
                return False
            result = [row.id for row in result_raw]
            return result


if __name__ == '__main__':
    r = Db.get_idioms_ids()
    print(r)
