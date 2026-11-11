# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authentication: register / login / logout / me + the API guard.

Sessions are opaque tokens in SQLite, sent as an HttpOnly cookie. The
Next.js dev proxy forwards cookies unchanged (same-origin), so the
browser needs no special handling.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .. import users as users_db
from ..deps import State, get_state
from ..schemas import AuthOut, LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def session_token(request: Request) -> str:
    return request.cookies.get(users_db.SESSION_COOKIE, "")


def current_user(request: Request) -> dict | None:
    """The authenticated user, if any. Also stored on request.state.user
    by the auth middleware."""
    user = getattr(request.state, "user", None)
    if user is not None:
        return user
    token = session_token(request)
    if not token:
        return None
    return users_db.get_session_user(get_state().jobs_db_path, token)


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Not authenticated")
    return user


def _auth_response(user: dict, status_code: int = 200) -> Response:
    """Login/register success: set the session cookie and return the user."""
    st = get_state()
    session = users_db.create_session(st.jobs_db_path, user["id"])
    response = JSONResponse(
        AuthOut(user=UserOut(**user)).model_dump(), status_code=status_code
    )
    response.set_cookie(
        users_db.SESSION_COOKIE,
        session["token"],
        max_age=users_db.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/register", response_model=AuthOut, status_code=201)
def register(body: RegisterIn) -> Response:
    st = get_state()
    try:
        user = users_db.create_user(st.jobs_db_path, body.username, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _auth_response(user, status_code=201)


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn) -> Response:
    st = get_state()
    user = users_db.verify_login(st.jobs_db_path, body.username, body.password)
    if user is None:
        raise HTTPException(401, "Invalid username or password")
    return _auth_response(user)


@router.post("/logout")
def logout(request: Request) -> dict:
    st = get_state()
    token = session_token(request)
    if token:
        users_db.delete_session(st.jobs_db_path, token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(users_db.SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=AuthOut)
def me(user: dict = Depends(require_user)) -> AuthOut:
    return AuthOut(user=UserOut(**user))
