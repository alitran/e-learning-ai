import asyncio
import logging
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select, update

from app.database import SessionLocal, engine
from app.documents import extract_pdf_sections, pdf_has_unextractable_pages
from app.models import Material, MaterialOCRJob, MaterialSection, utc_now

logger = logging.getLogger(__name__)
POLL_SECONDS = 3
OCR_TIMEOUT_SECONDS = 30 * 60


async def _claim_job() -> int | None:
    async with SessionLocal() as db:
        async with db.begin():
            result = await db.execute(
                select(MaterialOCRJob)
                .where(MaterialOCRJob.status == "queued")
                .order_by(MaterialOCRJob.created_at, MaterialOCRJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return None
            job.status = "processing"
            job.progress = 5
            job.attempts += 1
            job.error = None
            return job.id


async def _set_progress(job_id: int, progress: int) -> None:
    async with SessionLocal() as db:
        job = await db.get(MaterialOCRJob, job_id)
        if job is not None and job.status == "processing":
            job.progress = progress
            await db.commit()


async def _run_ocr(input_path: Path, output_path: Path) -> None:
    executable = shutil.which("ocrmypdf")
    if executable is None:
        raise RuntimeError("OCRmyPDF is not installed in the worker container.")

    process = await asyncio.create_subprocess_exec(
        executable,
        "--language",
        "vie+eng",
        "--mode",
        "skip",
        "--output-type",
        "pdf",
        "--quiet",
        str(input_path),
        str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=OCR_TIMEOUT_SECONDS
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("OCR exceeded the 30 minute processing limit.") from None

    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail[-4000:] or "OCRmyPDF failed.")


async def _complete_job(job_id: int, material_id: int, sections: list, extracted: str) -> None:
    async with SessionLocal() as db:
        async with db.begin():
            material = await db.get(Material, material_id)
            job = await db.get(MaterialOCRJob, job_id)
            if material is None or job is None:
                raise RuntimeError("The material or OCR job no longer exists.")

            await db.execute(
                delete(MaterialSection).where(MaterialSection.material_id == material_id)
            )
            material.extracted_text = extracted[:12_000]
            db.add_all(
                [
                    MaterialSection(
                        material_id=material_id,
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
            job.status = "completed"
            job.progress = 100
            job.error = None


async def _mark_failed(job_id: int) -> None:
    async with SessionLocal() as db:
        job = await db.get(MaterialOCRJob, job_id)
        if job is not None:
            job.status = "failed"
            job.progress = 0
            job.error = (
                "Không thể nhận dạng nội dung PDF. Hãy kiểm tra file hoặc tải bản PDF rõ nét hơn."
            )
            await db.commit()


async def _process_job(job_id: int) -> None:
    try:
        async with SessionLocal() as db:
            job = await db.get(MaterialOCRJob, job_id)
            material = await db.get(Material, job.material_id) if job is not None else None
            if job is None or material is None:
                raise RuntimeError("The material or OCR job no longer exists.")
            material_id = material.id
            source_path = Path(material.storage_path)

        if not source_path.is_file():
            raise RuntimeError("Uploaded PDF is missing from shared storage.")

        pdf_data = source_path.read_bytes()
        needs_ocr = pdf_has_unextractable_pages(pdf_data)
        sections, extracted = extract_pdf_sections(pdf_data)
        if needs_ocr:
            await _set_progress(job_id, 20)
            with tempfile.TemporaryDirectory(prefix="elearning-ocr-") as temp_dir:
                searchable_pdf = Path(temp_dir) / "searchable.pdf"
                await _run_ocr(source_path, searchable_pdf)
                await _set_progress(job_id, 85)
                sections, extracted = extract_pdf_sections(searchable_pdf.read_bytes())

        if not extracted.strip():
            raise RuntimeError("OCR produced no extractable text.")

        await _set_progress(job_id, 95)
        await _complete_job(job_id, material_id, sections, extracted)
        logger.info("OCR job %s completed for material %s", job_id, material_id)
    except Exception:
        logger.exception("OCR job %s failed", job_id)
        try:
            await _mark_failed(job_id)
        except Exception:
            logger.exception("Could not persist failure state for OCR job %s", job_id)


async def _recover_abandoned_jobs() -> None:
    cutoff = utc_now() - timedelta(hours=1)
    async with SessionLocal() as db:
        await db.execute(
            update(MaterialOCRJob)
            .where(
                MaterialOCRJob.status == "processing",
                MaterialOCRJob.updated_at < cutoff,
            )
            .values(status="queued", progress=0, error=None, updated_at=utc_now())
        )
        await db.commit()


async def run_worker() -> None:
    await _recover_abandoned_jobs()
    logger.info("Material OCR worker started; polling every %s seconds", POLL_SECONDS)
    try:
        while True:
            try:
                job_id = await _claim_job()
            except Exception:
                logger.exception("Unable to read OCR queue")
                await asyncio.sleep(POLL_SECONDS)
                continue

            if job_id is None:
                await asyncio.sleep(POLL_SECONDS)
                continue
            await _process_job(job_id)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
