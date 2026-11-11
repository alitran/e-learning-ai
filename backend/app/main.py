from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api import router
from app.config import settings
from app.database import SessionLocal, engine
from app.models import Base, Classroom, Course

DEFAULT_CLASSES = [(f"Lớp {grade}", f"Trung học cơ sở" if grade <= 9 else "Trung học phổ thông") for grade in range(6, 13)]
DEFAULT_COURSES = [
    ("math", "Toán", "Đại số, hình học và tư duy logic"),
    ("literature", "Ngữ văn", "Đọc hiểu, tiếng Việt và viết"),
    ("english", "Tiếng Anh", "Ngữ pháp, từ vựng và giao tiếp"),
    ("physics", "Vật lý", "Các hiện tượng và quy luật vật lý"),
    ("chemistry", "Hóa học", "Chất, phản ứng và ứng dụng"),
    ("biology", "Sinh học", "Sự sống và thế giới sinh vật"),
    ("history", "Lịch sử", "Sự kiện và tiến trình lịch sử"),
    ("geography", "Địa lý", "Tự nhiên, dân cư và kinh tế"),
    ("informatics", "Tin học", "Tư duy máy tính và công nghệ"),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        for name, level in DEFAULT_CLASSES:
            existing = await session.scalar(select(Classroom).where(Classroom.name == name))
            if existing is None:
                session.add(Classroom(name=name, level=level))
        for code, name, description in DEFAULT_COURSES:
            existing = await session.scalar(select(Course).where(Course.code == code))
            if existing is None:
                session.add(Course(code=code, name=name, description=description))
        await session.commit()
    yield
    await engine.dispose()


origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app = FastAPI(title="e-learning-ai API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "e-learning-ai"}
