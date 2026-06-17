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
