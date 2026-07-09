"""Worker main entry point.

Run with: `rq worker --url redis://... default`
The job functions are in `app.jobs.*` and are imported by RQ via
their fully-qualified module path (see `app.queue`).
"""

from __future__ import annotations


def main() -> None:
    """Placeholder for the worker process.

    The actual `rq worker` invocation lives in the Dockerfile / docker-compose
    so that RQ can manage the process lifecycle. This module exists so
    `python -m app.main` is a valid entry point and can run sanity checks.
    """
    from app.core.config import get_settings

    settings = get_settings()
    print(
        f"knicksiq-worker ready (env={settings.environment}, "
        f"test_mode={settings.test_mode}, redis={settings.redis_url})"
    )


if __name__ == "__main__":
    main()
