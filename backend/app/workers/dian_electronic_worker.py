"""Worker de habilitación DIAN separado del proceso HTTP.

Procesa la cola durable de pruebas y consultas de estado. Se mantiene separado
para que una respuesta lenta de DIAN no bloquee las solicitudes del usuario.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.config.settings import settings
from app.database import SessionLocal
from app.services.dian_electronic_habilitation_service import DianElectronicHabilitationService


logger = logging.getLogger("contamind.dian_electronic_worker")


async def process_available_jobs(*, max_jobs: int) -> int:
    processed = 0
    for _ in range(max_jobs):
        db = SessionLocal()
        try:
            document = await DianElectronicHabilitationService(db).process_next_job()
        except Exception:
            logger.exception("dian electronic worker failed before completing a job")
            db.rollback()
            break
        finally:
            db.close()
        if document is None:
            break
        processed += 1
        logger.info(
            "dian electronic job processed",
            extra={
                "document_id": str(document.id),
                "company_id": str(document.company_id),
                "status": document.status,
            },
        )
    return processed


async def serve_forever(*, max_jobs: int, poll_seconds: int) -> None:
    while True:
        processed = await process_available_jobs(max_jobs=max_jobs)
        if processed == 0:
            await asyncio.sleep(poll_seconds)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume pruebas DIAN de habilitación pendientes.")
    parser.add_argument("--once", action="store_true", help="Procesa un lote y termina.")
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=settings.PROVIDER_SYNC_WORKER_BATCH_SIZE,
        help="Máximo de trabajos por lote (1-100).",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _arguments()
    if not 1 <= args.max_jobs <= 100:
        raise SystemExit("--max-jobs debe estar entre 1 y 100.")
    if args.once:
        await process_available_jobs(max_jobs=args.max_jobs)
        return
    await serve_forever(
        max_jobs=args.max_jobs,
        poll_seconds=settings.PROVIDER_SYNC_WORKER_POLL_SECONDS,
    )


if __name__ == "__main__":
    asyncio.run(_main())
