import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


LESSON_HEADING = re.compile(
    r"^\s*bai\s+(?P<number>\d+(?:[a-z])?)\b(?P<rest>.*?)\s*$",
    re.IGNORECASE,
)
TABLE_OF_CONTENTS_TITLE = re.compile(
    r"^\s*(?:muc\s+luc|table\s+of\s+contents|contents)\b",
    re.IGNORECASE,
)
TABLE_OF_CONTENTS_ENTRY = re.compile(
    r"^\s*(?:bai|chuong|phan)\s+\d+\b.+\s+\d{1,4}\s*$",
    re.IGNORECASE,
)
LESSON_HEADING_WINDOW = 12


@dataclass(frozen=True)
class DocumentSection:
    ordinal: int
    kind: str
    title: str
    lesson_number: str | None
    start_page: int
    end_page: int
    content: str


def _fold_for_matching(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text).casefold()
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _lesson_heading(line: str) -> tuple[str, str] | None:
    if LESSON_HEADING.match(_fold_for_matching(line.strip())) is None:
        return None

    raw_match = re.match(
        r"^\s*\S+\s+(?P<number>\d+(?:[a-z])?)\b(?P<rest>.*?)\s*$",
        line,
        re.IGNORECASE,
    )
    if raw_match is None:
        return None
    return raw_match.group("number"), raw_match.group("rest").strip(" .:;–—-")


def _is_table_of_contents_page(page_text: str) -> bool:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    folded_lines = [_fold_for_matching(line) for line in lines]
    if any(TABLE_OF_CONTENTS_TITLE.match(line) for line in folded_lines[:6]):
        return True

    entry_count = sum(TABLE_OF_CONTENTS_ENTRY.match(line) is not None for line in folded_lines)
    return entry_count >= 2


def _content_pages_without_table_of_contents(pages: list[str]) -> list[tuple[int, str]]:
    content_pages: list[tuple[int, str]] = []
    inside_table_of_contents = False

    for page_number, page_text in enumerate(pages, start=1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        folded_lines = [_fold_for_matching(line) for line in lines]
        has_title = any(TABLE_OF_CONTENTS_TITLE.match(line) for line in folded_lines[:6])
        if has_title or _is_table_of_contents_page(page_text):
            inside_table_of_contents = True
            continue

        if inside_table_of_contents:
            entry_count = sum(
                TABLE_OF_CONTENTS_ENTRY.match(line) is not None for line in folded_lines
            )
            if entry_count >= 1:
                continue
            inside_table_of_contents = False

        content_pages.append((page_number, page_text))

    return content_pages


def pdf_has_unextractable_pages(pdf_data: bytes) -> bool:
    reader = PdfReader(BytesIO(pdf_data))
    return any(not (page.extract_text() or "").strip() for page in reader.pages)


def extract_pdf_sections(pdf_data: bytes) -> tuple[list[DocumentSection], str]:
    reader = PdfReader(BytesIO(pdf_data))
    pages = [
        (page.extract_text() or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        for page in reader.pages
    ]
    content_pages = _content_pages_without_table_of_contents(pages)
    full_text = "\n\n".join(page_text.strip() for _, page_text in content_pages if page_text.strip())
    if not full_text:
        return [], ""

    sections: list[DocumentSection] = []
    current_title = "Nội dung mở đầu trước bài đầu tiên"
    current_number: str | None = None
    current_heading_name: str | None = None
    current_start_page = content_pages[0][0]
    current_end_page = current_start_page
    current_lines: list[str] = []
    has_lesson = False

    def flush_section() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(
                DocumentSection(
                    ordinal=len(sections) + 1,
                    kind="intro" if current_number is None else "lesson",
                    title=current_title,
                    lesson_number=current_number,
                    start_page=current_start_page,
                    end_page=max(current_start_page, current_end_page),
                    content=content,
                )
            )

    for page_number, page_text in content_pages:
        nonempty_line_number = 0
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if line:
                nonempty_line_number += 1

            heading = (
                _lesson_heading(line)
                if line and nonempty_line_number <= LESSON_HEADING_WINDOW
                else None
            )
            if heading is not None:
                lesson_number, lesson_title = heading
                heading_name = _fold_for_matching(lesson_title)
                if current_number == lesson_number and current_heading_name == heading_name:
                    current_lines.append(raw_line.rstrip())
                    current_end_page = max(current_end_page, page_number)
                    continue

                flush_section()
                has_lesson = True
                current_number = lesson_number
                current_heading_name = heading_name
                current_title = lesson_title or f"Bài {current_number}"
                current_start_page = page_number
                current_end_page = page_number
                current_lines = [raw_line.rstrip()]
                continue

            current_lines.append(raw_line.rstrip())
            if line:
                current_end_page = page_number
        current_lines.append("")

    flush_section()
    lesson_sections = [section for section in sections if section.kind == "lesson"]
    if not has_lesson or not lesson_sections:
        return [
            DocumentSection(
                ordinal=1,
                kind="unsegmented",
                title="Toàn văn (chưa nhận diện bài)",
                lesson_number=None,
                start_page=content_pages[0][0],
                end_page=max(content_pages[-1][0], content_pages[0][0]),
                content=full_text,
            )
        ], full_text

    return [
        DocumentSection(
            ordinal=index,
            kind="lesson",
            title=section.title,
            lesson_number=section.lesson_number,
            start_page=section.start_page,
            end_page=section.end_page,
            content=section.content,
        )
        for index, section in enumerate(lesson_sections, start=1)
    ], full_text
