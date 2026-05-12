import os


def get_database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://fred:fred@localhost:5432/fred",
    )

