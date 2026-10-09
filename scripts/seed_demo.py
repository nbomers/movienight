"""Fill an empty database with made-up users and movies for local testing.

Usage: python -m scripts.seed_demo
All demo users get the password "demo-password".
"""

from datetime import datetime, timedelta, timezone

from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.models import Comment, Movie, Round, RoundGuest, User, Vote, VoteType

DEMO_PASSWORD = "demo-password"

# Posters are left out on purpose: the demo works without a TMDB key, and
# movies added through the search get their real posters.
MOVIES = [
    ("Inception", 27205, 2010, "Action, Science Fiction"),
    ("Spirited Away", 129, 2001, "Animation, Family, Fantasy"),
    ("Parasite", 496243, 2019, "Comedy, Thriller, Drama"),
    ("The Grand Budapest Hotel", 120467, 2014, "Comedy, Drama"),
    ("Mad Max: Fury Road", 76341, 2015, "Action, Adventure, Science Fiction"),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.query(User).filter(User.username != "admin").count():
            print("Database already has users, nothing to do.")
            return

        pw = hash_password(DEMO_PASSWORD)
        demo_admin = User(username="demo_admin", hashed_password=pw, is_admin=True)
        alex = User(username="alex", hashed_password=pw, is_regular=True)
        sam = User(username="sam", hashed_password=pw, is_regular=True)
        robin = User(username="robin", hashed_password=pw)  # guest
        db.add_all([demo_admin, alex, sam, robin])
        db.flush()

        now = datetime.now(timezone.utc)
        round_ = Round(name="Demo-Filmabend", starts_at=now, vote_deadline=now + timedelta(days=3))
        db.add(round_)
        db.flush()
        db.add(RoundGuest(round_id=round_.id, user_id=robin.id))

        submitters = [alex, sam, demo_admin, alex, robin]
        movies = []
        for (title, tmdb_id, year, genres), user in zip(MOVIES, submitters, strict=True):
            movie = Movie(
                title=title,
                tmdb_id=tmdb_id,
                release_year=year,
                genres=genres,
                submitted_by=user.id,
                round_id=round_.id,
            )
            db.add(movie)
            movies.append(movie)
        db.flush()

        votes = [
            (alex, movies[0], VoteType.up),
            (sam, movies[0], VoteType.up),
            (robin, movies[1], VoteType.superlike),
            (sam, movies[2], VoteType.up),
            (alex, movies[3], VoteType.down),
        ]
        for user, movie, vote_type in votes:
            db.add(Vote(user_id=user.id, movie_id=movie.id, vote_type=vote_type, round_id=round_.id))
        db.add(Comment(movie_id=movies[0].id, user_id=sam.id, text="Schon dreimal gesehen, trotzdem dabei."))
        db.commit()

    print(f"Demo data created. Log in as demo_admin, alex, sam or robin with password '{DEMO_PASSWORD}'.")


if __name__ == "__main__":
    main()
