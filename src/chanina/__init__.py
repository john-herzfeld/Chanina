from chanina.core.chanina import ChaninaApplication
from chanina.core.worker_session import WorkerSession


__all__ = [
    "ChaninaApplication",
    # Deprecated: kept only so `from chanina import WorkerSession` (and
    # isinstance checks against it) keep working. See
    # chanina.core.worker_session for the compatibility notes.
    "WorkerSession",
]
