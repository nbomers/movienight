from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey,
    Integer, String, Text, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum
import secrets


class VoteType(str, enum.Enum):
    up = "up"
    down = "down"
    superlike = "superlike"


class RoundStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class InviteType(str, enum.Enum):
    regular = "regular"
    guest = "guest"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_regular: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Stammgast
    # Part of every login token. Raising it (password change or reset) makes
    # all tokens issued before invalid. It starts at a random value because
    # SQLite reuses the id of a deleted user, and a new account with that id
    # must not accept the old account's tokens.
    token_version: Mapped[int] = mapped_column(
        Integer, default=lambda: secrets.randbits(31), nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    invite_tokens: Mapped[list["InviteToken"]] = relationship(
        "InviteToken", foreign_keys="InviteToken.created_by", back_populates="created_by_user",
    )
    movies: Mapped[list["Movie"]] = relationship(back_populates="submitted_by_user")
    votes: Mapped[list["Vote"]] = relationship(back_populates="user")
    comments: Mapped[list["Comment"]] = relationship(back_populates="user")
    round_access: Mapped[list["RoundGuest"]] = relationship(back_populates="user")


class InviteToken(Base):
    __tablename__ = "invite_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invite_type: Mapped[InviteType] = mapped_column(
        Enum(InviteType), default=InviteType.regular, nullable=False
    )

    created_by_user: Mapped["User"] = relationship(
        "User", foreign_keys=[created_by], back_populates="invite_tokens"
    )

    @property
    def is_expired(self) -> bool:
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

    @property
    def is_used(self) -> bool:
        if self.max_uses == 0:
            return False
        return self.use_count >= self.max_uses

    @property
    def is_valid(self) -> bool:
        return not self.is_expired and not self.is_used


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[RoundStatus] = mapped_column(
        Enum(RoundStatus), default=RoundStatus.active, nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vote_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    watched_movie_id: Mapped[int | None] = mapped_column(ForeignKey("movies.id"), nullable=True)

    movies: Mapped[list["Movie"]] = relationship(
        "Movie", foreign_keys="Movie.round_id", back_populates="round",
    )
    watched_movie: Mapped["Movie | None"] = relationship("Movie", foreign_keys=[watched_movie_id])
    guests: Mapped[list["RoundGuest"]] = relationship(back_populates="round", cascade="all, delete-orphan")

    @property
    def voting_closed(self) -> bool:
        """True once the vote deadline has passed. No votes or proposals then."""
        if self.vote_deadline is None:
            return False
        deadline = self.vote_deadline
        if deadline.tzinfo is None:  # SQLite drops the offset; stored as UTC
            deadline = deadline.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > deadline


class RoundGuest(Base):
    """Gäste die explizit für eine Runde eingeladen wurden."""
    __tablename__ = "round_guests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (UniqueConstraint("round_id", "user_id", name="uq_round_guest"),)

    round: Mapped["Round"] = relationship(back_populates="guests")
    user: Mapped["User"] = relationship(back_populates="round_access")


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genres: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trailer_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    round_id: Mapped[int | None] = mapped_column(ForeignKey("rounds.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rounds_survived: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    submitted_by_user: Mapped["User"] = relationship(back_populates="movies")
    round: Mapped["Round | None"] = relationship(back_populates="movies", foreign_keys=[round_id])
    votes: Mapped[list["Vote"]] = relationship(back_populates="movie", cascade="all, delete-orphan")
    comments: Mapped[list["Comment"]] = relationship(back_populates="movie", cascade="all, delete-orphan")


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), nullable=False)
    vote_type: Mapped[VoteType] = mapped_column(Enum(VoteType), nullable=False)
    round_id: Mapped[int | None] = mapped_column(ForeignKey("rounds.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (UniqueConstraint("user_id", "movie_id", "round_id", name="uq_vote_per_round"),)

    user: Mapped["User"] = relationship(back_populates="votes")
    movie: Mapped["Movie"] = relationship(back_populates="votes")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    movie: Mapped["Movie"] = relationship(back_populates="comments")
    user: Mapped["User"] = relationship(back_populates="comments")

