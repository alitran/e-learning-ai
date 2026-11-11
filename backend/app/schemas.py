from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=2, max_length=100)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetCompleteIn(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    classroom_id: int | None

    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ClassOut(BaseModel):
    id: int
    name: str
    level: str

    model_config = ConfigDict(from_attributes=True)


class CourseOut(BaseModel):
    id: int
    code: str
    name: str
    description: str
    prompt: str = ""
    materials: list[dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)


class CourseLessonTitleOut(BaseModel):
    id: int
    course_id: int
    classroom_id: int
    title: str
    ordinal: int
    volume: int | None

    model_config = ConfigDict(from_attributes=True)


class AIConfigIn(BaseModel):
    provider: Literal["demo", "openai", "ollama", "custom"] = "demo"
    model: str = Field(default="gpt-4o-mini", min_length=1, max_length=120)
    base_url: str = Field(default="https://api.openai.com/v1", min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=2000)
    clear_api_key: bool = False


class PromptIn(BaseModel):
    course_id: int
    prompt: str = Field(default="", max_length=10000)


class SettingsIn(AIConfigIn):
    classroom_id: int
    prompts: list[PromptIn] = []


class LessonCreateIn(BaseModel):
    course_id: int
    title: str = Field(min_length=2, max_length=255)


class ExerciseCreateIn(BaseModel):
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    count: int = Field(default=5, ge=1, le=20)
    instructions: str = Field(default="", max_length=2000)


class ExerciseAttemptIn(BaseModel):
    answers: list[str] = Field(min_length=1, max_length=20)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=3000)


class ExerciseUpdateIn(BaseModel):
    exercises: list[dict[str, Any]]


class LessonOut(BaseModel):
    id: int
    course_id: int
    course_name: str
    classroom_id: int
    classroom_name: str
    title: str
    content: str
    examples: list[dict[str, Any]]
    exercises: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

