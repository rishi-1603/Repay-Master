"""Request schemas for role management."""
from typing import Literal

from pydantic import BaseModel, Field


class RoleGrantRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    role: Literal["ops", "admin"]
