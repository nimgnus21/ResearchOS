import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.services.ingestion import resume_unfinished


class _RedactSecrets(logging.Filter):
    """Belt-and-braces: never let configured API keys reach the logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        s = get_settings()
        msg = record.getMessage()
        for secret in (s.llm_api_key, s.embedding_api_key):
            if secret and secret in msg:
                record.msg = msg.replace(secret, "***")
                record.args = ()
        return True


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for h in logging.getLogger().handlers:
    h.addFilter(_RedactSecrets())


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().storage_dir.mkdir(parents=True, exist_ok=True)
    n = resume_unfinished()
    if n:
        logging.getLogger(__name__).info("re-queued %d unfinished documents", n)
    yield


app = FastAPI(title="ResearchOS API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
