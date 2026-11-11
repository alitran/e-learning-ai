import json
import logging
import re
from typing import Any

import httpx

from app.models import AIConfig
from app.security import decrypt_secret


logger = logging.getLogger(__name__)


def _endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _extract_json(content: str) -> Any:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError("AI chưa trả về dữ liệu JSON hợp lệ.") from None


async def generate(config: AIConfig | None, system_prompt: str, user_prompt: str, *, json_mode: bool = False) -> Any:
    if config is None or config.provider == "demo":
        raise RuntimeError("demo_mode")
    api_key = decrypt_secret(config.encrypted_api_key)
    if config.provider != "ollama" and not api_key:
        raise ValueError("Hãy thêm API key trong trang Cấu hình trước khi tạo nội dung.")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.65,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=600, write=60, pool=15)) as client:
            response = await client.post(_endpoint(config.base_url), headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"AI provider trả về lỗi HTTP {exc.response.status_code}.") from None
    except httpx.TimeoutException:
        logger.warning("AI provider request timed out (provider=%s, model=%s)", config.provider, config.model)
        raise ValueError(
            "AI provider xử lý quá lâu. Hãy rút gọn Prompt hoặc tài liệu, hoặc kiểm tra tải của model."
        ) from None
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        logger.warning(
            "AI provider request failed (provider=%s, model=%s, error=%s)",
            config.provider,
            config.model,
            type(exc).__name__,
        )
        raise ValueError(
            "Không kết nối được AI provider. Hãy kiểm tra endpoint, model và trạng thái dịch vụ."
        ) from None
    return _extract_json(content) if json_mode else str(content)


def lesson_fallback(title: str, course_name: str, class_name: str, source_context: str) -> dict[str, Any]:
    context_note = "" if not source_context else "\n\n> Tài liệu PDF đã được lưu, nhưng chế độ Demo không phân tích nội dung tài liệu."
    return {
        "content": (
            f"# {title}\n\n## Mục tiêu bài học\nSau bài học, bạn có thể giải thích các khái niệm chính về {title}, "
            f"nhận biết cách áp dụng và tự kiểm tra kết quả.\n\n## 1. Khởi động\nHãy nghĩ về một tình huống đời sống có liên quan đến **{title}**. "
            f"Bài học môn {course_name} hôm nay sẽ kết nối kiến thức với ví dụ quen thuộc, phù hợp với {class_name}.\n\n"
            f"## 2. Kiến thức trọng tâm\n- **Khái niệm:** Nêu rõ định nghĩa và các từ khóa cần nhớ.\n"
            f"- **Cách hiểu:** Chia nội dung thành các bước nhỏ, kiểm tra từng bước trước khi chuyển tiếp.\n"
            f"- **Lưu ý:** Phân biệt điều kiện áp dụng và những trường hợp dễ nhầm lẫn.\n\n## 3. Tóm tắt\n"
            f"Ôn lại định nghĩa, quy trình giải quyết và tự giải thích vì sao phương pháp đó phù hợp với bài toán."
            f"{context_note}\n\n*Chế độ Demo tạo khung bài học mẫu. Chọn OpenAI, Ollama hoặc Tùy chỉnh trong Cấu hình để nhận nội dung AI đầy đủ.*"
        ),
        "examples": [
            {
                "title": "Ví dụ có hướng dẫn",
                "scenario": f"Áp dụng kiến thức {title} vào một bài toán gần gũi trong môn {course_name}.",
                "steps": ["Xác định dữ kiện và điều cần tìm.", "Chọn khái niệm hoặc quy tắc phù hợp.", "Giải từng bước và kiểm tra lại kết quả."],
                "answer": "Học viên tự trình bày lời giải; đối chiếu từng bước với phần kiến thức trọng tâm.",
            }
        ],
    }


def exercise_fallback(title: str, course_name: str, difficulty: str, count: int, instructions: str) -> list[dict[str, Any]]:
    levels = {"easy": "Dễ", "medium": "Trung bình", "hard": "Khó"}
    return [
        {
            "question": f"[{levels[difficulty]}] Câu {i + 1}: Hãy nêu một ý chính trong bài {title} ({course_name}) và giải thích bằng lời của bạn.",
            "choices": [],
            "answer": "Câu trả lời cần nêu đúng ý chính và giải thích mạch lạc bằng ví dụ hoặc lập luận phù hợp.",
            "explanation": "Tự kiểm tra xem câu trả lời đã có khái niệm, lập luận và ví dụ minh họa chưa.",
            "difficulty": difficulty,
        }
        for i in range(count)
    ]
