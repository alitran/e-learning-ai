import asyncio
import hashlib
import logging
import re
import secrets
import smtplib
import ssl
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai import exercise_fallback, generate, lesson_fallback
from app.config import settings
from app.database import get_db
from app.documents import extract_pdf_sections
from app.models import (
    AIConfig,
    Classroom,
    Course,
    CourseLessonTitle,
    CoursePrompt,
    ExerciseAttempt,
    Lesson,
    LessonMessage,
    Material,
    MaterialOCRJob,
    MaterialSection,
    PasswordResetToken,
    User,
    utc_now,
)
from app.schemas import (
    AskIn,
    ClassOut,
    CourseOut,
    CourseLessonTitleOut,
    ExerciseAttemptIn,
    ExerciseCreateIn,
    ExerciseUpdateIn,
    LessonCreateIn,
    LoginIn,
    PasswordResetCompleteIn,
    PasswordResetRequestIn,
    RegisterIn,
    SettingsIn,
    TokenOut,
    UserOut,
)
from app.security import create_access_token, encrypt_secret, get_current_user, hash_password, verify_password

router = APIRouter()
logger = logging.getLogger(__name__)
prompt_logger = logging.getLogger("uvicorn.error")

DEFAULT_LESSON_PROMPT = (
    "Bạn là gia sư tận tâm. Giảng giải chính xác bằng tiếng Việt, phù hợp với lớp học đã chọn. "
    "Chia kiến thức thành các mục rõ ràng, giải thích thuật ngữ, nêu ví dụ từng bước và kết thúc bằng phần tóm tắt. "
    "Nếu có tài liệu môn học, hãy dùng tài liệu đó làm nguồn chính; không bỏ qua nội dung liên quan. "
    "Không bịa dữ kiện hoặc số trang. Nếu tài liệu không đủ để trả lời, hãy nói rõ phần nào chưa có trong tài liệu; "
    "chỉ bổ sung kiến thức nền khi cần và phân biệt rõ đó là kiến thức bổ sung. "
    "Khi phù hợp, ghi nguồn theo tên tài liệu và khoảng trang được cung cấp. "
    "Nếu không có tài liệu, hãy tự soạn bài từ kiến thức nền của bạn. "
    "Trả về JSON gồm content (Markdown) và examples (mảng ví dụ)."
)
MATERIAL_CONTEXT_LIMIT = 32_000
MATERIAL_STOP_WORDS = {
    "bài", "học", "chương", "môn", "lớp", "và", "của", "theo", "trong", "được", "này",
    "những", "các", "một", "với", "cho", "từ", "đến", "về", "khi", "để", "có", "là",
    "tại", "như", "thế", "nào", "kiến", "thức", "hãy", "giải", "thích",
}


@dataclass(frozen=True)
class _MaterialSource:
    file_name: str
    title: str
    kind: str
    ordinal: int
    content: str
    start_page: int | None = None
    end_page: int | None = None


def _material_terms(text: str) -> set[str]:
    return {
        word.casefold()
        for word in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        if len(word) >= 2 and word.casefold() not in MATERIAL_STOP_WORDS
    }


def _material_excerpt(content: str, terms: set[str], max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    lowered = content.casefold()
    positions = [lowered.find(term) for term in terms]
    positions = [position for position in positions if position >= 0]
    start = max(0, min(positions) - min(1800, max_chars // 4)) if positions else 0
    start = min(start, max(0, len(content) - max_chars))
    excerpt = content[start : start + max_chars].strip()
    if start:
        excerpt = "[… trích đoạn …]\n" + excerpt
    if start + max_chars < len(content):
        excerpt += "\n[… còn nội dung khác trong bài …]"
    return excerpt


def _build_material_context(
    sources: list[_MaterialSource], course_name: str, lesson_title: str
) -> str:
    if not sources:
        return ""

    query_terms = _material_terms(f"{course_name} {lesson_title}")
    ranked: list[tuple[int, _MaterialSource]] = []
    for source in sources:
        title_terms = _material_terms(source.title)
        lowered = source.content.casefold()
        score = 8 * len(query_terms & title_terms)
        score += sum(min(lowered.count(term), 4) for term in query_terms)
        ranked.append((score, source))

    ranked.sort(
        key=lambda item: (
            -item[0],
            0 if item[1].kind in {"lesson", "chapter"} else 1,
            item[1].ordinal,
        )
    )
    matched = [item for item in ranked if item[0] > 0]
    selected = (matched or ranked[:2])[:5]

    blocks: list[str] = []
    remaining = MATERIAL_CONTEXT_LIMIT
    for _, source in selected:
        page_label = ""
        if source.start_page is not None and source.end_page is not None:
            page_label = f" | trang {source.start_page}-{source.end_page}"
        header = f"[Tài liệu: {source.file_name} | {source.title}{page_label}]"
        budget = min(10_000, remaining - len(header) - 2)
        if budget < 300:
            break
        excerpt = _material_excerpt(source.content, query_terms, budget)
        block = f"{header}\n{excerpt}"
        blocks.append(block)
        remaining -= len(block) + 2
        if remaining < 300:
            break
    return "\n\n".join(blocks)


DEFAULT_EXERCISE_PROMPT = (
    "Tạo bài tập bám sát bài giảng, đúng môn học và trình độ lớp. Trả về JSON với exercises là mảng; "
    "mỗi phần tử có question, choices (mảng lựa chọn hoặc mảng rỗng), answer, explanation, difficulty. "
    "Với câu trắc nghiệm, answer phải là nguyên văn một lựa chọn trong choices hoặc chỉ ký tự A/B/C/D; "
    "để phần giải thích riêng trong explanation. Với câu tự luận, answer là đáp án tham khảo ngắn gọn."
)


def _http_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def _send_password_reset_email(to_email: str, reset_url: str) -> None:
    sender = settings.smtp_from or settings.smtp_username
    if (
        settings.smtp_from
        and "@" not in settings.smtp_from
        and settings.smtp_username
        and "@" in settings.smtp_username
    ):
        sender = formataddr((settings.smtp_from, settings.smtp_username))
    if not settings.smtp_host or not sender:
        raise RuntimeError("Password reset email is not configured")

    message = EmailMessage()
    message["Subject"] = "Đặt lại mật khẩu e-learning-ai"
    message["From"] = sender
    message["To"] = to_email
    message.set_content(
        "Bạn vừa yêu cầu đặt lại mật khẩu cho tài khoản e-learning-ai.\n\n"
        f"Mở liên kết sau để tạo mật khẩu mới (liên kết hết hạn sau 30 phút):\n{reset_url}\n\n"
        "Nếu bạn không thực hiện yêu cầu này, hãy bỏ qua email này."
    )

    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=15,
            context=ssl.create_default_context(),
        ) as server:
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            server.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password or "")
        server.send_message(message)


async def _get_ai_config(db: AsyncSession, user_id: int) -> AIConfig | None:
    return await db.get(AIConfig, user_id)


async def _get_course(db: AsyncSession, course_id: int) -> Course:
    course = await db.get(Course, course_id)
    if course is None:
        raise _http_error(404, "Không tìm thấy môn học.")
    return course


def _lesson_title_key(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title).casefold()
    plain = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def _lesson_title_from_section(section: MaterialSection) -> str:
    title = section.title.strip()
    if section.lesson_number and not title.casefold().startswith("bài "):
        return f"Bài {section.lesson_number}: {title}" if title else f"Bài {section.lesson_number}"
    return title


async def _ensure_lesson_sections_indexed(
    db: AsyncSession, materials: list[Material]
) -> None:
    if not materials:
        return

    material_ids = [material.id for material in materials]
    indexed_result = await db.execute(
        select(MaterialSection.material_id, MaterialSection.kind).where(
            MaterialSection.material_id.in_(material_ids)
        )
    )
    section_kinds: dict[int, set[str]] = {}
    for material_id, kind in indexed_result.all():
        section_kinds.setdefault(material_id, set()).add(kind)

    reindexed = False
    for material in materials:
        kinds = section_kinds.get(material.id, set())
        needs_reindex = not kinds or (
            bool(kinds & {"chapter", "whole_document"}) and "lesson" not in kinds
        )
        if not needs_reindex:
            continue
        file_path = Path(material.storage_path)
        try:
            file_path.resolve().relative_to(settings.upload_dir.resolve())
        except ValueError:
            logger.warning("Skipping material outside upload directory (material_id=%s)", material.id)
            continue
        if not file_path.is_file():
            continue
        try:
            sections, extracted = extract_pdf_sections(file_path.read_bytes())
        except Exception:
            logger.exception("Could not reindex material sections (material_id=%s)", material.id)
            continue
        if not extracted.strip():
            continue

        await db.execute(
            delete(MaterialSection).where(MaterialSection.material_id == material.id)
        )
        material.extracted_text = extracted[:12_000]
        db.add_all(
            [
                MaterialSection(
                    material_id=material.id,
                    ordinal=section.ordinal,
                    kind=section.kind,
                    lesson_number=section.lesson_number,
                    title=section.title[:255],
                    start_page=section.start_page,
                    end_page=section.end_page,
                    content=section.content,
                )
                for section in sections
            ]
        )
        reindexed = True

    if reindexed:
        await db.commit()


async def _get_owned_lesson(db: AsyncSession, lesson_id: int, user_id: int) -> Lesson:
    result = await db.execute(
        select(Lesson)
        .where(Lesson.id == lesson_id, Lesson.user_id == user_id)
        .options(selectinload(Lesson.course), selectinload(Lesson.classroom))
    )
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise _http_error(404, "Không tìm thấy bài học.")
    return lesson


def _lesson_dict(lesson: Lesson) -> dict[str, Any]:
    return {
        "id": lesson.id,
        "course_id": lesson.course_id,
        "course_name": lesson.course.name,
        "classroom_id": lesson.classroom_id,
        "classroom_name": lesson.classroom.name,
        "title": lesson.title,
        "content": lesson.content,
        "examples": lesson.examples or [],
        "exercises": lesson.exercises or [],
        "created_at": lesson.created_at,
        "updated_at": lesson.updated_at,
    }


def _normalize_exercise_answer(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
    return "".join(character for character in decomposed if character.isalnum())


def _strip_choice_label(value: str) -> str:
    return re.sub(r"^\s*\(?\s*(?:[A-D]|\d+)\s*[).:,-]\s*", "", value, count=1, flags=re.IGNORECASE).strip()


def _grade_choice(exercise: dict[str, Any], response: str) -> tuple[int | None, int | None, bool]:
    choices = [str(choice).strip() for choice in exercise.get("choices", []) if choice is not None]
    selected_index = next((index for index, choice in enumerate(choices) if choice == response.strip()), None)
    if selected_index is None:
        return None, None, False

    answer = str(exercise.get("answer", "")).strip()
    answer_letter = re.match(
        r"^(?:đáp án(?: đúng)?\s*[:\-]?\s*)?\(?\s*([A-D])(?:\s*[).:,-]\s*|$)",
        answer,
        flags=re.IGNORECASE,
    )
    if answer_letter:
        correct_index = ord(answer_letter.group(1).upper()) - ord("A")
        if correct_index >= len(choices):
            correct_index = None
    else:
        normalized_answer = _normalize_exercise_answer(_strip_choice_label(answer))
        correct_index = next(
            (
                index
                for index, choice in enumerate(choices)
                if _normalize_exercise_answer(_strip_choice_label(choice)) == normalized_answer
            ),
            None,
        )
    return selected_index, correct_index, correct_index is not None and selected_index == correct_index


def _exercise_attempt_dict(
    attempt: ExerciseAttempt,
    lesson_title: str,
    course_name: str,
) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "lesson_id": attempt.lesson_id,
        "lesson_title": lesson_title,
        "course_name": course_name,
        "total_questions": attempt.total_questions,
        "objective_count": attempt.objective_count,
        "correct_count": attempt.correct_count,
        "written_count": attempt.written_count,
        "score_percent": (
            round(attempt.correct_count * 100 / attempt.objective_count)
            if attempt.objective_count
            else None
        ),
        "results": attempt.results or [],
        "submitted_at": attempt.submitted_at,
    }


@router.post("/auth/password-reset-requests")
async def request_password_reset(
    payload: PasswordResetRequestIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if not settings.smtp_host or not (settings.smtp_from or settings.smtp_username):
        raise _http_error(
            503,
            "Chức năng đặt lại mật khẩu chưa được cấu hình gửi email. Hãy cấu hình SMTP cho API.",
        )

    email = str(payload.email).lower().strip()
    user = await db.scalar(select(User).where(User.email == email))
    if user is not None:
        now = utc_now()
        recent_request = await db.scalar(
            select(PasswordResetToken.id)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at >= now - timedelta(seconds=60),
            )
            .limit(1)
        )
        if recent_request is None:
            raw_token = secrets.token_urlsafe(32)
            await db.execute(
                delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
            )
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                    expires_at=now + timedelta(minutes=30),
                )
            )
            await db.commit()
            fragment = urlencode({"token": raw_token})
            reset_url = f"{settings.app_base_url.rstrip('/')}/reset-password#{fragment}"
            try:
                await asyncio.to_thread(_send_password_reset_email, email, reset_url)
            except Exception:
                logger.exception("Could not send password reset email")

    return {
        "message": "Nếu email khớp với tài khoản, hướng dẫn đặt lại mật khẩu sẽ được gửi đến bạn."
    }


@router.post("/auth/password-resets")
async def complete_password_reset(
    payload: PasswordResetCompleteIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    now = utc_now()
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    reset_record = await db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.expires_at > now,
        )
    )
    if reset_record is None:
        raise _http_error(400, "Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.")

    user = await db.get(User, reset_record.user_id)
    if user is None:
        raise _http_error(400, "Liên kết đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.")

    user.password_hash = hash_password(payload.new_password)
    await db.execute(
        delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    await db.commit()
    return {"message": "Mật khẩu đã được đặt lại. Hãy đăng nhập bằng mật khẩu mới."}


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    email = str(payload.email).lower().strip()
    user = User(email=email, display_name=payload.display_name.strip(), password_hash=hash_password(payload.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _http_error(409, "Email này đã được sử dụng.") from None
    await db.refresh(user)
    return {"access_token": create_access_token(user.id), "user": user}


@router.post("/auth/login", response_model=TokenOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(select(User).where(User.email == str(payload.email).lower().strip()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise _http_error(401, "Email hoặc mật khẩu chưa chính xác.")
    return {"access_token": create_access_token(user.id), "user": user}


@router.get("/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/classes", response_model=list[ClassOut])
async def list_classes(db: AsyncSession = Depends(get_db)) -> list[Classroom]:
    result = await db.execute(select(Classroom).order_by(Classroom.id))
    return list(result.scalars().all())


@router.get("/courses", response_model=list[CourseOut])
async def list_courses(db: AsyncSession = Depends(get_db)) -> list[Course]:
    result = await db.execute(select(Course).order_by(Course.name))
    return list(result.scalars().all())


@router.get(
    "/courses/{course_id}/lesson-titles",
    response_model=list[CourseLessonTitleOut],
)
async def list_course_lesson_titles(
    course_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CourseLessonTitle]:
    await _get_course(db, course_id)
    if user.classroom_id is None:
        return []
    result = await db.execute(
        select(CourseLessonTitle)
        .where(
            CourseLessonTitle.user_id == user.id,
            CourseLessonTitle.classroom_id == user.classroom_id,
            CourseLessonTitle.course_id == course_id,
        )
        .order_by(CourseLessonTitle.ordinal, CourseLessonTitle.id)
    )
    return list(result.scalars().all())


@router.post("/courses/{course_id}/lesson-titles/sync")
async def sync_course_lesson_titles(
    course_id: int,
    classroom_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    await _get_course(db, course_id)
    classroom = await db.get(Classroom, classroom_id)
    if classroom is None:
        raise _http_error(404, "Không tìm thấy lớp học.")
    if user.classroom_id != classroom.id:
        raise _http_error(403, "Lớp học đồng bộ không khớp với lớp bạn đã chọn trong cấu hình.")

    materials_result = await db.execute(
        select(Material)
        .where(Material.user_id == user.id, Material.course_id == course_id)
        .order_by(Material.created_at, Material.id)
    )
    materials = list(materials_result.scalars().all())
    if not materials:
        raise _http_error(
            409,
            "Môn học chưa có PDF. Hãy tải lên tài liệu Kết nối tri thức (Tập 1 và/hoặc Tập 2) trước khi đồng bộ.",
        )

    pending_job = await db.scalar(
        select(MaterialOCRJob.id)
        .where(
            MaterialOCRJob.material_id.in_([material.id for material in materials]),
            MaterialOCRJob.status.in_({"queued", "processing"}),
        )
        .limit(1)
    )
    if pending_job is not None:
        raise _http_error(409, "PDF môn học đang được xử lý. Hãy đợi OCR hoàn tất rồi đồng bộ lại.")

    await _ensure_lesson_sections_indexed(db, materials)
    rows_result = await db.execute(
        select(MaterialSection, Material.file_name, Material.created_at)
        .join(Material, Material.id == MaterialSection.material_id)
        .where(
            Material.user_id == user.id,
            Material.course_id == course_id,
            MaterialSection.kind == "lesson",
        )
    )

    extracted_titles: list[tuple[int | None, datetime, int, str, str, str]] = []
    for section, file_name, created_at in rows_result.all():
        title = _lesson_title_from_section(section).strip()[:255]
        title_key = _lesson_title_key(title)
        if not title or not title_key:
            continue
        folded_file_name = _lesson_title_key(file_name)
        volume_match = re.search(r"\btap\s*([12])\b", folded_file_name)
        volume = int(volume_match.group(1)) if volume_match else None
        extracted_titles.append(
            (volume, created_at, section.ordinal, title, title_key, file_name[:255])
        )

    extracted_titles.sort(
        key=lambda item: (
            item[0] is None,
            item[0] or 99,
            item[1],
            item[2],
        )
    )
    unique_titles: dict[str, tuple[int | None, str, str]] = {}
    for volume, _, _, title, title_key, file_name in extracted_titles:
        unique_titles.setdefault(title_key, (volume, title, file_name))

    if not unique_titles:
        raise _http_error(
            422,
            "Chưa tìm thấy tiêu đề dạng Bài trong PDF đã xử lý. Hãy kiểm tra file hoặc nhập tiêu đề trực tiếp ở trang học.",
        )

    await db.execute(
        delete(CourseLessonTitle).where(
            CourseLessonTitle.user_id == user.id,
            CourseLessonTitle.classroom_id == classroom.id,
            CourseLessonTitle.course_id == course_id,
        )
    )
    lesson_titles = [
        CourseLessonTitle(
            user_id=user.id,
            classroom_id=classroom.id,
            course_id=course_id,
            title=title,
            title_key=title_key,
            ordinal=ordinal,
            volume=volume,
            source_file_name=file_name,
            school_year="2026-2027",
            book_series="Kết nối tri thức với cuộc sống",
        )
        for ordinal, (title_key, (volume, title, file_name)) in enumerate(
            unique_titles.items(),
            start=1,
        )
    ]
    db.add_all(lesson_titles)
    await db.commit()
    return {
        "course_id": course_id,
        "classroom_id": classroom.id,
        "school_year": "2026-2027",
        "book_series": "Kết nối tri thức với cuộc sống",
        "count": len(lesson_titles),
        "titles": [CourseLessonTitleOut.model_validate(item) for item in lesson_titles],
    }


@router.get("/settings")
async def get_settings(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, Any]:
    classes_result = await db.execute(select(Classroom).order_by(Classroom.id))
    courses_result = await db.execute(select(Course).order_by(Course.name))
    config = await _get_ai_config(db, user.id)
    prompt_result = await db.execute(select(CoursePrompt).where(CoursePrompt.user_id == user.id))
    prompts = {item.course_id: item.prompt for item in prompt_result.scalars().all()}
    materials_result = await db.execute(
        select(Material).where(Material.user_id == user.id).order_by(Material.created_at.desc())
    )
    section_counts_result = await db.execute(
        select(
            MaterialSection.material_id,
            func.sum(case((MaterialSection.kind == "lesson", 1), else_=0)),
            func.count(MaterialSection.id),
        )
        .join(Material, Material.id == MaterialSection.material_id)
        .where(Material.user_id == user.id)
        .group_by(MaterialSection.material_id)
    )
    section_counts = {
        material_id: (int(lesson_count), int(section_count))
        for material_id, lesson_count, section_count in section_counts_result.all()
    }
    materials = materials_result.scalars().all()
    job_result = (
        await db.execute(
            select(MaterialOCRJob).where(
                MaterialOCRJob.material_id.in_([item.id for item in materials])
            )
        )
        if materials
        else None
    )
    jobs_by_material = {
        job.material_id: job for job in job_result.scalars().all()
    } if job_result is not None else {}
    materials_by_course: dict[int, list[dict[str, Any]]] = {}
    for item in materials:
        job = jobs_by_material.get(item.id)
        processing_status = job.status if job else (
            "completed" if item.extracted_text or section_counts.get(item.id, (0, 0))[1] else "legacy"
        )
        materials_by_course.setdefault(item.course_id, []).append(
            {
                "id": item.id,
                "file_name": item.file_name,
                "lesson_count": section_counts.get(item.id, (0, 0))[0],
                "section_count": section_counts.get(item.id, (0, 0))[1],
                "processing_status": processing_status,
                "processing_progress": job.progress if job else (100 if processing_status == "completed" else 0),
                "processing_error": job.error if job else None,
                "created_at": item.created_at,
            }
        )
    courses = [
        {
            "id": course.id,
            "code": course.code,
            "name": course.name,
            "description": course.description,
            "prompt": prompts.get(course.id, ""),
            "materials": materials_by_course.get(course.id, []),
        }
        for course in courses_result.scalars().all()
    ]
    return {
        "classroom_id": user.classroom_id,
        "classes": [ClassOut.model_validate(item) for item in classes_result.scalars().all()],
        "provider": config.provider if config else "demo",
        "model": config.model if config else "gpt-4o-mini",
        "base_url": config.base_url if config else "https://api.openai.com/v1",
        "has_api_key": bool(config and config.encrypted_api_key),
        "courses": courses,
    }


@router.put("/settings")
async def update_settings(
    payload: SettingsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    classroom = await db.get(Classroom, payload.classroom_id)
    if classroom is None:
        raise _http_error(404, "Không tìm thấy lớp học.")

    classroom_changed = (
        user.classroom_id is not None and user.classroom_id != classroom.id
    )
    removed_materials: list[Material] = []
    removed_material_paths: list[Path] = []
    if classroom_changed:
        materials_result = await db.execute(
            select(Material).where(Material.user_id == user.id)
        )
        removed_materials = list(materials_result.scalars().all())
        for material in removed_materials:
            file_path = Path(material.storage_path)
            try:
                file_path.resolve().relative_to(settings.upload_dir.resolve())
            except ValueError:
                raise _http_error(500, "Đường dẫn file tài liệu không hợp lệ.") from None
            removed_material_paths.append(file_path)

        await db.execute(
            delete(CourseLessonTitle).where(CourseLessonTitle.user_id == user.id)
        )

        material_ids = [material.id for material in removed_materials]
        if material_ids:
            await db.execute(
                delete(MaterialSection).where(MaterialSection.material_id.in_(material_ids))
            )
            await db.execute(
                delete(MaterialOCRJob).where(MaterialOCRJob.material_id.in_(material_ids))
            )
            await db.execute(delete(Material).where(Material.id.in_(material_ids)))

    config = await _get_ai_config(db, user.id)
    if config is None:
        config = AIConfig(user_id=user.id)
        db.add(config)
    config.provider = payload.provider
    config.model = payload.model.strip()
    config.base_url = payload.base_url.strip().rstrip("/")
    if payload.api_key:
        config.encrypted_api_key = encrypt_secret(payload.api_key)
    elif payload.clear_api_key:
        config.encrypted_api_key = None
    user.classroom_id = classroom.id
    for item in payload.prompts:
        if await db.get(Course, item.course_id) is None:
            raise _http_error(404, f"Không tìm thấy môn học {item.course_id}.")
        result = await db.execute(
            select(CoursePrompt).where(
                CoursePrompt.user_id == user.id,
                CoursePrompt.course_id == item.course_id,
            )
        )
        prompt = result.scalar_one_or_none()
        if prompt is None:
            prompt = CoursePrompt(user_id=user.id, course_id=item.course_id, prompt=item.prompt.strip())
            db.add(prompt)
        else:
            prompt.prompt = item.prompt.strip()
    await db.commit()

    cleanup_failed = False
    for material, file_path in zip(removed_materials, removed_material_paths):
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            cleanup_failed = True
            logger.exception(
                "Could not remove uploaded material after classroom change (user_id=%s, material_id=%s)",
                user.id,
                material.id,
            )

    response = await get_settings(db, user)
    if removed_materials:
        response["materials_removed"] = len(removed_materials)
    if cleanup_failed:
        response["material_cleanup_warning"] = (
            "Đã đổi lớp và xóa dữ liệu tài liệu trong database, nhưng một số file PDF chưa xóa được khỏi ổ lưu trữ."
        )
    return response


@router.post("/materials", status_code=status.HTTP_202_ACCEPTED)
async def upload_material(
    course_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    course = await _get_course(db, course_id)
    filename = Path(file.filename or "tai-lieu.pdf").name
    if Path(filename).suffix.lower() != ".pdf" or (
        file.content_type and file.content_type not in {"application/pdf", "application/octet-stream"}
    ):
        raise _http_error(415, "Chỉ hỗ trợ tài liệu PDF.")
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise _http_error(413, f"File vượt quá giới hạn {settings.max_upload_mb} MB.")

    destination = settings.upload_dir / str(user.id) / str(course_id)
    destination.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    file_path = destination / stored_name
    material = Material(
        user_id=user.id,
        course_id=course.id,
        file_name=filename,
        storage_path=str(file_path),
        extracted_text="",
    )
    try:
        file_path.write_bytes(data)
        db.add(material)
        await db.flush()
        job = MaterialOCRJob(material_id=material.id, status="queued", progress=0)
        db.add(job)
        await db.commit()
    except Exception:
        await db.rollback()
        file_path.unlink(missing_ok=True)
        raise

    await db.refresh(material)
    return {
        "id": material.id,
        "file_name": material.file_name,
        "status": "queued",
        "progress": 0,
        "lesson_count": 0,
        "section_count": 0,
        "created_at": material.created_at,
    }


@router.delete("/materials/{material_id}")
async def delete_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    material = await db.scalar(
        select(Material).where(Material.id == material_id, Material.user_id == user.id)
    )
    if material is None:
        raise _http_error(404, "Không tìm thấy tài liệu.")

    file_path = Path(material.storage_path)
    try:
        file_path.resolve().relative_to(settings.upload_dir.resolve())
    except ValueError:
        raise _http_error(500, "Đường dẫn file tài liệu không hợp lệ.") from None

    await db.execute(
        delete(MaterialSection).where(MaterialSection.material_id == material.id)
    )
    await db.execute(
        delete(MaterialOCRJob).where(MaterialOCRJob.material_id == material.id)
    )
    await db.delete(material)
    await db.commit()

    try:
        file_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.exception("Could not remove uploaded material file %s", material.id)
        raise _http_error(
            500,
            "Dữ liệu tài liệu đã được xóa nhưng không thể xóa file PDF trên ổ lưu trữ.",
        ) from exc

    return {"message": "Đã xóa file PDF, dữ liệu trích xuất và trạng thái OCR."}


@router.get("/materials/{material_id}/status")
async def get_material_status(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    material = await db.scalar(
        select(Material).where(Material.id == material_id, Material.user_id == user.id)
    )
    if material is None:
        raise _http_error(404, "Không tìm thấy tài liệu.")

    job = await db.scalar(
        select(MaterialOCRJob).where(MaterialOCRJob.material_id == material.id)
    )
    status_value = job.status if job else (
        "completed" if material.extracted_text else "legacy"
    )
    return {
        "id": material.id,
        "status": status_value,
        "progress": job.progress if job else (100 if status_value == "completed" else 0),
        "error": job.error if job else None,
    }


@router.post("/lessons", status_code=status.HTTP_201_CREATED)
async def create_lesson(
    payload: LessonCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if user.classroom_id is None:
        raise _http_error(400, "Hãy chọn lớp học trong trang Cấu hình trước.")
    course = await _get_course(db, payload.course_id)
    classroom = await db.get(Classroom, user.classroom_id)
    if classroom is None:
        raise _http_error(400, "Lớp học đã chọn không còn tồn tại. Hãy chọn lại trong Cấu hình.")
    config = await _get_ai_config(db, user.id)
    prompt_result = await db.execute(
        select(CoursePrompt).where(
            CoursePrompt.user_id == user.id,
            CoursePrompt.course_id == course.id,
        )
    )
    course_prompt = prompt_result.scalar_one_or_none()
    materials_result = await db.execute(
        select(Material).where(
            Material.user_id == user.id, Material.course_id == course.id
        )
    )
    materials = materials_result.scalars().all()
    if materials:
        pending_job = await db.scalar(
            select(MaterialOCRJob.id)
            .where(
                MaterialOCRJob.material_id.in_([item.id for item in materials]),
                MaterialOCRJob.status.in_({"queued", "processing"}),
            )
            .limit(1)
        )
        if pending_job is not None:
            raise _http_error(
                409,
                "Tài liệu môn học đang được nhận dạng chữ. Hãy chờ xử lý xong rồi tạo bài học.",
            )

        await _ensure_lesson_sections_indexed(db, list(materials))

    sections_result = await db.execute(
        select(MaterialSection, Material.file_name)
        .join(Material, Material.id == MaterialSection.material_id)
        .where(Material.user_id == user.id, Material.course_id == course.id)
        .order_by(Material.created_at.desc(), MaterialSection.ordinal)
    )
    sources: list[_MaterialSource] = []
    section_rows = sections_result.all()
    section_material_ids: set[int] = set()
    for section, file_name in section_rows:
        section_material_ids.add(section.material_id)
        sources.append(
            _MaterialSource(
                file_name=file_name,
                title=section.title,
                kind=section.kind,
                ordinal=section.ordinal,
                content=section.content,
                start_page=section.start_page,
                end_page=section.end_page,
            )
        )
    for material in materials:
        if material.id not in section_material_ids and material.extracted_text:
            sources.append(
                _MaterialSource(
                    file_name=material.file_name,
                    title="Văn bản trích xuất trước đây",
                    kind="legacy",
                    ordinal=0,
                    content=material.extracted_text,
                )
            )
    material_context = _build_material_context(sources, course.name, payload.title.strip())
    system_prompt = DEFAULT_LESSON_PROMPT
    if course_prompt and course_prompt.prompt:
        system_prompt += f"\n\nYêu cầu riêng cho môn {course.name}:\n{course_prompt.prompt}"
    source_instructions = (
        "Dùng các trích đoạn tài liệu môn học sau làm căn cứ chính; ghi nguồn theo tên tài liệu và trang khi thông tin đó có sẵn. "
        "Nếu tài liệu không đề cập chủ đề, hãy nói rõ và chỉ bổ sung kiến thức nền khi cần.\n"
        + material_context
        if material_context
        else "Môn học chưa có tài liệu đã tải lên; hãy tự phân tích chủ đề bằng kiến thức nền và soạn bài chi tiết."
    )
    user_prompt = (
        f"Lớp học: {classroom.name} ({classroom.level}).\nMôn học: {course.name}.\n"
        f"Tiêu đề bài học: {payload.title.strip()}.\n"
        f"Hãy tạo bài giảng có giải thích chi tiết, các bước học dễ theo dõi và ít nhất một ví dụ cụ thể.\n"
        f"{source_instructions}"
    )
    prompt_logger.info(
        "Lesson generation prompt before AI call (user_id=%s, course_id=%s, provider=%s, model=%s):\n"
        "SYSTEM PROMPT:\n%s\nUSER PROMPT:\n%s",
        user.id,
        course.id,
        config.provider if config else "demo",
        config.model if config else "demo",
        system_prompt,
        user_prompt,
    )
    try:
        generated = await generate(config, system_prompt, user_prompt, json_mode=True)
        if not isinstance(generated, dict):
            raise ValueError("AI chưa trả về dữ liệu bài giảng hợp lệ.")
        content = str(generated.get("content", "")).strip()
        examples = generated.get("examples", [])
        if not content:
            raise ValueError("AI chưa trả về nội dung bài giảng.")
    except RuntimeError as exc:
        if str(exc) != "demo_mode":
            raise
        generated = lesson_fallback(payload.title.strip(), course.name, classroom.name, material_context)
        content, examples = generated["content"], generated["examples"]
    except ValueError as exc:
        raise _http_error(502, str(exc)) from None
    lesson = Lesson(
        user_id=user.id,
        course_id=course.id,
        classroom_id=classroom.id,
        title=payload.title.strip(),
        content=content,
        examples=examples if isinstance(examples, list) else [],
        exercises=[],
    )
    db.add(lesson)
    await db.commit()
    return _lesson_dict(await _get_owned_lesson(db, lesson.id, user.id))


@router.get("/lessons")
async def list_lessons(
    course_id: int | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    query = (
        select(Lesson)
        .where(Lesson.user_id == user.id)
        .options(selectinload(Lesson.course), selectinload(Lesson.classroom))
        .order_by(Lesson.created_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    if course_id is not None:
        query = query.where(Lesson.course_id == course_id)
    result = await db.execute(query)
    return [_lesson_dict(item) for item in result.scalars().all()]


@router.get("/lessons/{lesson_id}")
async def get_lesson(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return _lesson_dict(await _get_owned_lesson(db, lesson_id, user.id))


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    await db.execute(
        delete(ExerciseAttempt).where(ExerciseAttempt.lesson_id == lesson.id)
    )
    await db.execute(
        delete(LessonMessage).where(LessonMessage.lesson_id == lesson.id)
    )
    await db.delete(lesson)
    await db.commit()
    return {"message": "Đã xóa bài giảng cùng dữ liệu hỏi đáp và kết quả nộp bài."}


@router.post("/lessons/{lesson_id}/exercises")
async def create_exercises(
    lesson_id: int,
    payload: ExerciseCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    config = await _get_ai_config(db, user.id)
    prompt_result = await db.execute(
        select(CoursePrompt).where(CoursePrompt.user_id == user.id, CoursePrompt.course_id == lesson.course_id)
    )
    course_prompt = prompt_result.scalar_one_or_none()
    system_prompt = DEFAULT_EXERCISE_PROMPT
    if course_prompt and course_prompt.prompt:
        system_prompt += f"\n\nLưu ý riêng của môn học:\n{course_prompt.prompt}"
    user_prompt = (
        f"Môn học: {lesson.course.name}.\nBài học: {lesson.title}.\nNội dung bài học:\n{lesson.content[:18000]}\n\n"
        f"Tạo {payload.count} bài tập mức độ {payload.difficulty}. "
        f"Yêu cầu thêm của học viên: {payload.instructions or 'Không có'}. "
        "Đảm bảo câu hỏi đa dạng, có đáp án và giải thích ngắn gọn."
    )
    try:
        generated = await generate(config, system_prompt, user_prompt, json_mode=True)
        exercises = generated.get("exercises", []) if isinstance(generated, dict) else []
        if not isinstance(exercises, list) or not exercises:
            raise ValueError("AI chưa trả về danh sách bài tập hợp lệ.")
    except RuntimeError as exc:
        if str(exc) != "demo_mode":
            raise
        exercises = exercise_fallback(lesson.title, lesson.course.name, payload.difficulty, payload.count, payload.instructions)
    except ValueError as exc:
        raise _http_error(502, str(exc)) from None
    lesson.exercises = exercises
    lesson.updated_at = datetime.utcnow()
    await db.commit()
    return lesson.exercises


@router.patch("/lessons/{lesson_id}/exercises")
async def update_exercises(
    lesson_id: int,
    payload: ExerciseUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    lesson.exercises = payload.exercises
    lesson.updated_at = datetime.utcnow()
    await db.commit()
    return lesson.exercises


@router.post("/lessons/{lesson_id}/exercise-attempts", status_code=status.HTTP_201_CREATED)
async def submit_exercise_attempt(
    lesson_id: int,
    payload: ExerciseAttemptIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    exercises = lesson.exercises or []
    if not exercises:
        raise _http_error(400, "Bài học chưa có bài tập để nộp.")
    if len(payload.answers) != len(exercises):
        raise _http_error(422, "Số câu trả lời không khớp với bộ bài tập hiện tại.")

    results: list[dict[str, Any]] = []
    objective_count = 0
    written_count = 0
    correct_count = 0
    for index, exercise in enumerate(exercises):
        response = payload.answers[index].strip()
        if not response:
            raise _http_error(422, f"Câu {index + 1} chưa có câu trả lời.")
        if len(response) > 5000:
            raise _http_error(422, f"Câu trả lời {index + 1} vượt quá 5.000 ký tự.")

        choices = [str(choice).strip() for choice in exercise.get("choices", []) if choice is not None]
        selected_choice_index: int | None = None
        correct_choice_index: int | None = None
        correct: bool | None = None
        if choices:
            objective_count += 1
            selected_choice_index, correct_choice_index, correct = _grade_choice(exercise, response)
            correct_count += int(correct)
        else:
            written_count += 1

        results.append(
            {
                "question": str(exercise.get("question", "")),
                "choices": choices,
                "answer": str(exercise.get("answer", "")),
                "explanation": str(exercise.get("explanation", "")),
                "difficulty": str(exercise.get("difficulty", "")),
                "response": response,
                "correct": correct,
                "selected_choice_index": selected_choice_index,
                "correct_choice_index": correct_choice_index,
            }
        )

    attempt = ExerciseAttempt(
        user_id=user.id,
        lesson_id=lesson.id,
        total_questions=len(exercises),
        objective_count=objective_count,
        correct_count=correct_count,
        written_count=written_count,
        results=results,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return _exercise_attempt_dict(attempt, lesson.title, lesson.course.name)


@router.get("/exercise-attempts")
async def list_exercise_attempts(
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(ExerciseAttempt, Lesson.title, Course.name)
        .join(Lesson, Lesson.id == ExerciseAttempt.lesson_id)
        .join(Course, Course.id == Lesson.course_id)
        .where(ExerciseAttempt.user_id == user.id)
        .order_by(ExerciseAttempt.submitted_at.desc(), ExerciseAttempt.id.desc())
        .limit(limit)
    )
    return [
        _exercise_attempt_dict(attempt, lesson_title, course_name)
        for attempt, lesson_title, course_name in result.all()
    ]


@router.get("/lessons/{lesson_id}/exercise-attempts")
async def list_lesson_exercise_attempts(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    result = await db.execute(
        select(ExerciseAttempt)
        .where(ExerciseAttempt.lesson_id == lesson.id, ExerciseAttempt.user_id == user.id)
        .order_by(ExerciseAttempt.submitted_at.desc(), ExerciseAttempt.id.desc())
    )
    return [
        _exercise_attempt_dict(attempt, lesson.title, lesson.course.name)
        for attempt in result.scalars().all()
    ]


@router.post("/lessons/{lesson_id}/ask")
async def ask_lesson(
    lesson_id: int,
    payload: AskIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    lesson = await _get_owned_lesson(db, lesson_id, user.id)
    config = await _get_ai_config(db, user.id)
    system_prompt = (
        "Bạn là gia sư đang giải đáp thắc mắc dựa trên bài học. Trả lời bằng tiếng Việt, rõ ràng, "
        "đưa ví dụ ngắn khi hữu ích và nói rõ nếu nội dung không có trong bài học."
    )
    user_prompt = f"Bài học '{lesson.title}' ({lesson.course.name}):\n{lesson.content[:16000]}\n\nCâu hỏi: {payload.question}"
    try:
        answer = await generate(config, system_prompt, user_prompt)
    except RuntimeError as exc:
        if str(exc) != "demo_mode":
            raise
        answer = (
            f"Bạn đang hỏi về **{lesson.title}**. Hãy đối chiếu câu hỏi với phần kiến thức trọng tâm và ví dụ trong bài. "
            "Chế độ Demo không gọi mô hình AI; hãy cấu hình provider trong Cấu hình để nhận lời giải thích theo câu hỏi cụ thể."
        )
    except ValueError as exc:
        raise _http_error(502, str(exc)) from None
    message = LessonMessage(lesson_id=lesson.id, question=payload.question, answer=answer)
    db.add(message)
    await db.commit()
    return {"answer": answer, "created_at": message.created_at}


@router.get("/lessons/{lesson_id}/messages")
async def list_lesson_messages(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    await _get_owned_lesson(db, lesson_id, user.id)
    result = await db.execute(
        select(LessonMessage).where(LessonMessage.lesson_id == lesson_id).order_by(LessonMessage.created_at)
    )
    return [
        {"id": item.id, "question": item.question, "answer": item.answer, "created_at": item.created_at}
        for item in result.scalars().all()
    ]
