from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_active_round, get_round_access
from app.models import Comment, Movie, User
from app.schemas import CommentCreate, CommentResponse

router = APIRouter(prefix="/movies", tags=["comments"])

MAX_COMMENTS_PER_MOVIE = 10


def _visible_movie(db: Session, movie_id: int, user: User) -> Movie:
    """Guests only see the movies of the round they were invited to."""
    query = db.query(Movie).filter(Movie.id == movie_id, Movie.is_active == True)  # noqa
    if not (user.is_admin or user.is_regular):
        active_round = get_active_round(db)
        query = query.filter(Movie.round_id == (active_round.id if active_round else -1))
    movie = query.first()
    if not movie:
        raise HTTPException(status_code=404, detail="Film nicht gefunden")
    return movie


@router.get("/{movie_id}/comments", response_model=list[CommentResponse])
def get_comments(movie_id: int, db: Session = Depends(get_db), current_user=Depends(get_round_access)):
    _visible_movie(db, movie_id, current_user)
    comments = (
        db.query(Comment)
        .filter(Comment.movie_id == movie_id)
        .order_by(Comment.created_at)
        .all()
    )
    result = []
    for c in comments:
        cr = CommentResponse.model_validate(c)
        cr.username = c.user.username if c.user else "?"
        result.append(cr)
    return result


@router.post("/{movie_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def add_comment(
    movie_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_round_access),
):
    _visible_movie(db, movie_id, current_user)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Kommentar darf nicht leer sein")
    # Spam protection
    existing_count = db.query(Comment).filter(
        Comment.movie_id == movie_id,
        Comment.user_id == current_user.id
    ).count()
    if existing_count >= MAX_COMMENTS_PER_MOVIE:
        raise HTTPException(status_code=400, detail=f"Maximal {MAX_COMMENTS_PER_MOVIE} Kommentare pro Film")
    comment = Comment(movie_id=movie_id, user_id=current_user.id, text=text)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    cr = CommentResponse.model_validate(comment)
    cr.username = current_user.username
    return cr


@router.delete("/{movie_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    movie_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_round_access),
):
    comment = db.query(Comment).filter(Comment.id == comment_id, Comment.movie_id == movie_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Kommentar nicht gefunden")
    if comment.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Nicht erlaubt")
    db.delete(comment)
    db.commit()
