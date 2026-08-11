"""Worker para consumir la cola persistente de sincronizaciones de proveedores.

Se ejecuta como proceso independiente del servidor FastAPI para que una
sincronizaci\u00f3n lenta no agote workers HTTP. La cola y el cursor viven en la
base de datos, por lo que reiniciar este proceso no pierde trabajos.
"""

import argparse
import asyncio
import logging

from app.config.settings import settings
from app.database import SessionLocal
from app.services.provider_connection_service import ProviderConnectionService

logger = logging.getLogger("contamind.provider_sync_worker")


async def process_available_jobs(*, max_jobs: int) -> int:
    """Procesa como m\u00e1ximo ``max_jobs`` p\u00e1ginas disponibles."""

    processed = 0
    for _ in range(max_jobs):
        db = SessionLocal()
        try:
            job = await ProviderConnectionService(db).process_next_sync_job()
        except Exception:
            logger.exception("provider sync worker failed before completing a job")
            db.rollback()
            break
        finally:
            db.close()
        if job is None:
            break
        processed += 1
        logger.info(
            "provider sync job processed",
            extra={
                "job_id": str(job.id),
                "data_source_id": str(job.data_source_id),
                "provider": job.provider_id,
                "status": job.status.value,
            },
        )
    return processed


async def serve_forever(*, max_jobs: int, poll_seconds: int) -> None:
    """Consume trabajos continuamente, esperando solo si no hay trabajo listo."""

    while True:
        processed = await process_available_jobs(max_jobs=max_jobs)
        if processed == 0:
            await asyncio.sleep(poll_seconds)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume sincronizaciones externas pendientes.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Procesa un lote disponible y termina; \u00fatil para un scheduler.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=settings.PROVIDER_SYNC_WORKER_BATCH_SIZE,
        help="M\u00e1ximo de p\u00e1ginas por lote (1-100).",
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
