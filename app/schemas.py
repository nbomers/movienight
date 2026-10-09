from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.models import InviteType, RoundStatus, VoteType


def _assume_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; they are stored as UTC. Without an offset
    # in the JSON, browsers would interpret them as local time.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


UtcDatetime = Annotated[datetime, AfterValidator(_assume_utc)]


class RegisterRequest(BaseModel):
    invite_token: str = Field(max_length=64)
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool
    is_regular: bool
    created_at: UtcDatetime
    model_config = {"from_attributes": True}


class InviteTokenCreate(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=8760)
    max_uses: int = Field(default=1, ge=0, le=100)
    invite_type: InviteType = InviteType.regular
    label: str | None = Field(default=None, max_length=100)


class InviteTokenResponse(BaseModel):
    id: int
    token: str
    expires_at: UtcDatetime
    is_used: bool = False
    is_expired: bool = False
    max_uses: int
    use_count: int
    invite_type: InviteType = InviteType.regular
    label: str | None = None
    created_at: UtcDatetime
    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, obj) -> "InviteTokenResponse":
        data = cls.model_validate(obj)
        data.is_used = obj.is_used
        data.is_expired = obj.is_expired
        return data


class MovieCreate(BaseModel):
    model_config = {"str_strip_whitespace": True}

    title: str = Field(min_length=1, max_length=255)
    tmdb_id: int | None = Field(default=None, ge=1)
    overview: str | None = Field(default=None, max_length=5000)
    # TMDB image paths look like "/abc123.jpg"; anything else is not a poster.
    poster_path: str | None = Field(default=None, max_length=255, pattern=r"^/[A-Za-z0-9_.-]+$")
    release_year: int | None = Field(default=None, ge=1870, le=2100)
    genres: str | None = Field(default=None, max_length=255)
    # Only YouTube watch links, which is what the TMDB lookup produces. This
    # also rules out javascript: URLs ending up in an href.
    trailer_url: str | None = Field(
        default=None,
        max_length=500,
        pattern=r"^https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{1,64}$",
    )


class MovieResponse(BaseModel):
    id: int
    title: str
    tmdb_id: int | None
    overview: str | None
    poster_path: str | None
    release_year: int | None
    genres: str | None
    trailer_url: str | None
    submitted_by: int
    submitted_by_username: str = ""
    round_id: int | None
    is_active: bool
    rounds_survived: int
    created_at: UtcDatetime
    upvotes: int = 0
    downvotes: int = 0
    superlikes: int = 0
    user_vote: VoteType | None = None
    superlike_available: bool = True
    comment_count: int = 0
    superlike_usernames: list[str] = []
    read_only: bool = False
    model_config = {"from_attributes": True}


class VoteRequest(BaseModel):
    vote_type: VoteType


class VoteResponse(BaseModel):
    id: int
    user_id: int
    movie_id: int
    vote_type: VoteType
    round_id: int | None
    created_at: UtcDatetime
    model_config = {"from_attributes": True}


class RoundCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    starts_at: datetime
    vote_deadline: str | None = None  # ISO string, interpreted as Europe/Berlin
    max_rounds_before_removal: int = Field(default=4, ge=1, le=52)


class RoundResponse(BaseModel):
    id: int
    name: str
    status: RoundStatus
    starts_at: UtcDatetime
    ends_at: UtcDatetime | None
    vote_deadline: UtcDatetime | None
    watched_movie_id: int | None
    created_at: UtcDatetime
    model_config = {"from_attributes": True}


class WatchedEntry(BaseModel):
    round_id: int
    round_name: str
    watched_at: UtcDatetime | None
    movie_id: int
    movie_tmdb_id: int | None
    movie_title: str
    movie_poster_path: str | None
    movie_release_year: int | None
    movie_genres: str | None
    submitted_by_username: str


class AppConfig(BaseModel):
    max_movies_per_user: int
    tmdb_enabled: bool


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class CommentResponse(BaseModel):
    id: int
    movie_id: int
    user_id: int
    username: str = ""
    text: str
    created_at: UtcDatetime
    model_config = {"from_attributes": True}


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=72)
    model_config = {"str_strip_whitespace": True}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=8, max_length=72)


class InviteLabelUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    model_config = {"str_strip_whitespace": True}


class RoundRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model_config = {"str_strip_whitespace": True}


class DeadlineUpdate(BaseModel):
    vote_deadline: str | None = None  # ISO string, interpreted as Europe/Berlin


# ── Round Guests ──────────────────────────────────────────────────────────────

class RoundGuestAdd(BaseModel):
    user_id: int


class RoundGuestResponse(BaseModel):
    id: int
    round_id: int
    user_id: int
    username: str = ""
    added_at: UtcDatetime
    model_config = {"from_attributes": True}
