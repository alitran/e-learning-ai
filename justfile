default:
    @just --list

# Install the backend and frontend dependencies.
install:
    cd backend && uv sync
    cd web && npm install

# Start the MySQL service for local API and Vite development.
db-up:
    docker compose up -d db

# Start the FastAPI development server (set DATABASE_URL host to 127.0.0.1 in local shell).
api:
    cd backend && DATABASE_URL="mysql+asyncmy://elearning:change-this-local-password@127.0.0.1:3306/elearning_ai?charset=utf8mb4" uv run uvicorn app.main:app --reload --port 8000

# Start the OCR worker in a separate terminal after the API is available.
worker:
    cd backend && uv run python -m app.ocr_worker

# Start the Vue development server.
web:
    cd web && npm run dev

# Start all services behind Nginx.
up:
    docker compose up --build

# Stop the Docker stack.
down:
    docker compose down

# Follow Docker service logs.
logs:
    docker compose logs -f

# Build the production frontend bundle.
build:
    cd web && npm run build
