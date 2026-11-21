import logging

import uvicorn

from .app import create_app
from .settings import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    s = Settings()
    uvicorn.run(create_app(s), host=s.host, port=s.port)


if __name__ == "__main__":
    main()
