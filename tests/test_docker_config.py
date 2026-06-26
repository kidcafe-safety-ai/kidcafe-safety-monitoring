from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_api_dockerfile_uses_minimal_api_runtime() -> None:
    dockerfile = read_file("Dockerfile.api")

    assert "python:" in dockerfile
    assert "slim" in dockerfile
    assert "requirements-api.txt" in dockerfile
    assert "uvicorn" in dockerfile
    assert "src.api.main:app" in dockerfile
    assert "--host" in dockerfile
    assert "0.0.0.0" in dockerfile
    assert "--port" in dockerfile
    assert "8000" in dockerfile
    assert "data/zones" in dockerfile
    assert "frontend" not in dockerfile


def test_api_requirements_exclude_vision_dependencies() -> None:
    requirements = read_file("requirements-api.txt")

    assert "fastapi==0.111.0" in requirements
    assert "uvicorn[standard]==0.30.1" in requirements
    assert "pydantic==2.7.1" in requirements

    excluded = [
        "torch",
        "torchvision",
        "torchaudio",
        "ultralytics",
        "opencv-python",
        "streamlit",
        "matplotlib",
    ]
    for package_name in excluded:
        assert package_name not in requirements


def test_compose_exposes_api_and_persists_sqlite_outputs() -> None:
    compose = read_file("docker-compose.yml")

    assert "kidcafe-api" in compose
    assert "Dockerfile.api" in compose
    assert "8000:8000" in compose
    assert "KIDCAFE_DB_PATH" in compose
    assert "/app/outputs/kidcafe_events.db" in compose
    assert "./outputs:/app/outputs" in compose
    assert "frontend" not in compose


def test_dockerignore_excludes_runtime_artifacts() -> None:
    dockerignore = read_file(".dockerignore")

    required_patterns = [
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "outputs",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        "frontend/node_modules",
        "frontend/dist",
        "*.pt",
        "*.onnx",
        "*.mp4",
        "*.avi",
        "*.mov",
    ]
    for pattern in required_patterns:
        assert pattern in dockerignore
