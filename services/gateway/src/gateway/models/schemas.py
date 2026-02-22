"""Pydantic models for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# --- Auth requests ---

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


# --- Auth responses ---

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str = "user"
    status: str = "active"
    created_at: datetime


class SessionResponse(BaseModel):
    user: UserResponse
    expires_at: datetime


# --- Health ---

class ServiceHealth(BaseModel):
    service: str
    status: str  # "healthy" | "unhealthy" | "unreachable"
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str = "gateway"
    version: str = "0.0.1"
    services: list[ServiceHealth] | None = None
