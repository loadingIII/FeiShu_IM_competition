from contextvars import ContextVar, Token
from typing import Optional
user_id: ContextVar[Optional[str]] = ContextVar('user_id', default=None)


def set_user_id(id):
    return user_id.set(id)


def reset_user_id(token: Token) -> None:
    user_id.reset(token)


def get_user_id() -> Optional[str]:
    return user_id.get()



