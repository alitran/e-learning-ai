# e-learning-ai

Ứng dụng học tập cá nhân hóa với FastAPI, Vue 3, MySQL và Nginx. Người học tạo tài khoản, chọn lớp, cấu hình AI theo môn, tải tài liệu PDF, tạo bài giảng, hỏi đáp và luyện tập theo mức độ. Lịch sử bài học được lưu theo môn học.

## Chạy nhanh bằng Docker

Cần Docker Desktop đang chạy.

```bash
cp .env.example .env
docker compose up --build
```

Mở <http://localhost:8080>. MySQL được khởi tạo tự động; lần đầu có thể mất một phút để tải image và cài dependencies. Backend có thêm worker OCR chạy riêng trong Docker Compose. Worker dùng Tesseract với tiếng Việt và tiếng Anh; file PDF được lưu trước, sau đó xử lý nền và cập nhật trạng thái trên trang **Cấu hình**. Tạo tài khoản ở trang đăng nhập, sau đó chọn lớp và môn học.

Trước khi lưu API key thật, thay `APP_SECRET_KEY` trong `.env` bằng giá trị riêng (có thể tạo bằng `openssl rand -hex 32`) và giữ khóa đó ổn định để backend giải mã lại key đã lưu.

Để bật **Quên mật khẩu**, cấu hình SMTP trong `.env`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` và chọn `SMTP_USE_TLS` (thường dùng cổng 587) hoặc `SMTP_USE_SSL` (thường dùng cổng 465). Đặt `APP_BASE_URL` thành địa chỉ người học mở, mặc định `http://localhost:8080`. Không commit thông tin SMTP.

## Chạy backend/frontend riêng khi phát triển

Cần Docker, uv, Node.js 20+ và npm. Cách này dùng MySQL trong compose, còn FastAPI/Vite chạy trực tiếp trên máy. Để chạy OCR worker trực tiếp trên macOS, cài thêm Tesseract có language data vie và eng, qpdf và Ghostscript; Docker Compose cài sẵn các công cụ này trong image backend.

```bash
cp .env.example .env
docker compose up -d db
cd backend
uv sync
DATABASE_URL="mysql+asyncmy://elearning:change-this-local-password@127.0.0.1:3306/elearning_ai?charset=utf8mb4" uv run uvicorn app.main:app --reload --port 8000
```

Lệnh trên dùng thông tin kết nối mẫu. Nếu bạn đổi user/password/database trong `.env`, cập nhật URL chỉ dùng cho lệnh backend trực tiếp. `.env` mặc định vẫn giữ host `db` để các container kết nối nhau.

Trong terminal khác:

```bash
cd web && npm install && npm run dev
```

Mở <http://localhost:5173>. API docs ở <http://localhost:8000/docs>.

## AI

- **Demo** hoạt động không cần API key và sinh nội dung mẫu để thử toàn bộ luồng local.
- **OpenAI** và **Tùy chỉnh** dùng API tương thích OpenAI Chat Completions.
- **Ollama** dùng endpoint tương thích OpenAI, mặc định `http://localhost:11434/v1`. Nếu backend chạy trong Docker và Ollama chạy trên host, đặt endpoint thành `http://host.docker.internal:11434/v1`.
- API key được mã hóa trước khi lưu DB bằng khóa dẫn xuất từ `APP_SECRET_KEY`. Không gửi key về trình duyệt sau khi lưu.

## Tính năng hiện có

- Đăng ký, đăng nhập, đặt lại mật khẩu qua liên kết email dùng một lần và bảo vệ API bằng JWT.
- Chọn một lớp; danh sách lớp và môn học mẫu được seed khi backend khởi động lần đầu.
- Cấu hình provider, model, endpoint, API key và prompt riêng theo môn.
- Upload PDF theo môn; worker OCR xử lý PDF scan bằng OCRmyPDF/Tesseract tiếng Việt + tiếng Anh, chia nội dung theo từng tiêu đề “Bài ...”, loại các trang mục lục và lưu từng bài vào database.
- Tác vụ OCR được xếp hàng trong MySQL và chạy ngoài request upload để tránh timeout. Trạng thái được cập nhật trên trang Cấu hình.
- Khi chạy API/frontend trực tiếp để phát triển, mở thêm một terminal và chạy lệnh just worker.
- Tạo bài giảng, hỏi đáp theo nội dung bài và sinh bài tập từ dễ đến khó.
- Chỉnh sửa bài tập bằng yêu cầu bổ sung; nội dung mới được lưu trong lịch sử.
- Lịch sử được nhóm theo môn học.

## Cấu trúc

```text
backend/app/       FastAPI API, SQLAlchemy models, auth, AI provider và OCR worker
web/src/           Vue 3 + TypeScript SPA
nginx/             Reverse proxy cho UI và API
docker-compose.yml MySQL + backend + frontend + Nginx
```

Đây là nền tảng MVP: lớp/môn học mẫu được seed trong code; phân quyền giáo viên, quản trị lớp và quản lý tài liệu nâng cao có thể bổ sung sau.
