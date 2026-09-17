from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class EmailRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class RegisterRequest(EmailRequest):
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=1024)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized_name = value.strip()
        if not normalized_name:
            raise ValueError("Name must not contain only whitespace.")
        return normalized_name

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password must not contain only whitespace.")
        return value


class LoginRequest(EmailRequest):
    password: str = Field(min_length=1, max_length=1024)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    is_active: bool
    is_admin: bool = False
    password_configured: bool = False
    is_email_verified: bool = False


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not contain only whitespace.")
        return value


class PasswordChangeRequest(BaseModel):
    current_password: str | None = Field(default=None, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


class AccountDeleteRequest(BaseModel):
    password: str | None = Field(default=None, max_length=1024)
    confirmation: str = Field(max_length=20)


class ForgotPasswordRequest(EmailRequest):
    pass


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    new_password: str = Field(min_length=8, max_length=1024)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=20, max_length=500)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
    total: int


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthResponse(TokenResponse):
    user: UserResponse


class LogoutResponse(BaseModel):
    success: bool = True
