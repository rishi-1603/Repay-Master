"""Request/response schemas for auth + saved-scenario history."""
from typing import Any

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, description="Minimum 8 characters.")


class RegisterResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ScenarioCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    params: dict[str, Any] = Field(description="Loan/risk inputs the client wants to recall later.")


class ScenarioRead(BaseModel):
    id: int
    label: str
    params: dict[str, Any]
    created_at: str
