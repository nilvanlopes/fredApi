import os


def get_database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://fred:fred@localhost:5432/fred",
    )


def get_weekly_attendance_capacity() -> int:
    return int(os.getenv("WEEKLY_ATTENDANCE_CAPACITY", "24"))


def get_single_game_price_cents() -> int:
    return int(os.getenv("SINGLE_GAME_PRICE_CENTS", "750"))


def get_monthly_subscription_price_cents() -> int:
    return int(os.getenv("MONTHLY_SUBSCRIPTION_PRICE_CENTS", "1250"))


def get_conversation_import_max_bytes() -> int:
    return int(os.getenv("CONVERSATION_IMPORT_MAX_BYTES", "2000000"))


def get_conversation_ai_base_url() -> str:
    return os.getenv("CONVERSATION_AI_BASE_URL", "").strip()


def get_conversation_ai_api_key() -> str:
    return os.getenv("CONVERSATION_AI_API_KEY", "").strip()


def get_conversation_ai_model() -> str:
    return os.getenv("CONVERSATION_AI_MODEL", "").strip()


def get_conversation_ai_confidence_threshold() -> float:
    return float(os.getenv("CONVERSATION_AI_CONFIDENCE_THRESHOLD", "0.90"))


def get_conversation_ai_batch_messages() -> int:
    return int(os.getenv("CONVERSATION_AI_BATCH_MESSAGES", "20"))


def get_conversation_ai_batch_chars() -> int:
    return int(os.getenv("CONVERSATION_AI_BATCH_CHARS", "12000"))


def get_conversation_ai_attempts() -> int:
    return int(os.getenv("CONVERSATION_AI_ATTEMPTS", "2"))


def get_conversation_ai_timeout_seconds() -> float:
    return float(os.getenv("CONVERSATION_AI_TIMEOUT_SECONDS", "240"))


def get_ollama_manage_service() -> bool:
    return _read_bool_env("OLLAMA_MANAGE_SERVICE", default=True)


def get_ollama_shutdown_when_done() -> bool:
    return _read_bool_env("OLLAMA_SHUTDOWN_WHEN_DONE", default=True)


def get_ollama_pull_model_when_missing() -> bool:
    return _read_bool_env("OLLAMA_PULL_MODEL_WHEN_MISSING", default=True)


def get_ollama_enable_gpu() -> bool:
    return _read_bool_env("OLLAMA_ENABLE_GPU", default=True)


def get_ollama_startup_timeout_seconds() -> float:
    return float(os.getenv("OLLAMA_STARTUP_TIMEOUT_SECONDS", "180"))


def get_ollama_poll_interval_seconds() -> float:
    return float(os.getenv("OLLAMA_POLL_INTERVAL_SECONDS", "2"))


def get_ollama_compose_file() -> str | None:
    value = os.getenv("OLLAMA_COMPOSE_FILE")
    if value is None:
        return ""
    normalized = value.strip()
    if normalized.lower() in {"none", "null", "off", "false"}:
        return None
    return normalized


def get_ollama_docker_socket() -> str:
    return os.getenv("OLLAMA_DOCKER_SOCKET", "/var/run/docker.sock").strip()


def get_ollama_container_name() -> str:
    return os.getenv("OLLAMA_CONTAINER_NAME", "fred-ollama").strip() or "fred-ollama"


def get_ollama_image() -> str:
    return os.getenv("OLLAMA_IMAGE", "ollama/ollama:latest").strip() or "ollama/ollama:latest"


def get_ollama_volume() -> str:
    return os.getenv("OLLAMA_VOLUME", "ollama_ollama-data").strip() or "ollama_ollama-data"


def get_ollama_network() -> str:
    return os.getenv("OLLAMA_NETWORK", "n8n").strip() or "n8n"


def _read_bool_env(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default
