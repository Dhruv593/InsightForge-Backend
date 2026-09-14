from app.api.google_auth import cookie_policy
from app.core.config import Settings


def test_managed_postgres_urls_use_psycopg_driver() -> None:
    assert Settings.use_psycopg_driver("postgres://user:pass@db/app") == (
        "postgresql+psycopg://user:pass@db/app"
    )
    assert Settings.use_psycopg_driver("postgresql://user:pass@db/app") == (
        "postgresql+psycopg://user:pass@db/app"
    )


def test_google_nonce_cookie_is_cross_site_only_over_https() -> None:
    assert cookie_policy("https://insightforge.vercel.app") == {
        "secure": True,
        "samesite": "none",
    }
    assert cookie_policy("http://localhost:5173") == {
        "secure": False,
        "samesite": "lax",
    }
