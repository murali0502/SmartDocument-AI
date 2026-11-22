import uvicorn

from smartdoc.config import Settings
from smartdoc.logging import logging_config


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "smartdoc.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=logging_config(settings.log_level),
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
