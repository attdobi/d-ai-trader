"""Run a shadow scorer without waiting on it in the trading decision path.

One hosted comparison may be outstanding per process. Audit logging attaches
after the actual prompt's served IDs are known. Configuration is injected.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decisions-compare")
_AUDIT_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decisions-audit")
_SLOT = BoundedSemaphore(1)


def submit_shadow(scorer, *args, log=print, **kwargs):
    """Submit a comparison; return a Future or None when a request is pending."""
    if not _SLOT.acquire(blocking=False):
        log("Decisions comparison skipped: previous comparison still running")
        return None
    try:
        future = _POOL.submit(scorer, *args, **kwargs)
    except Exception:
        _SLOT.release()
        raise
    future.add_done_callback(lambda _future: _SLOT.release())
    return future


def record_when_ready(job, engine, config_hash, prompt_version, run_id, *,
                      served_ids=(), local_result=None, source_input_id=None, recorder=None, log=print):
    """Attach an audit writer and return immediately, including on slow APIs."""
    if job is None:
        return
    actual_ids = frozenset(served_ids)

    def persist(future):
        try:
            if recorder is None:
                from .decisions_log import record_shadow
                write = record_shadow
            else:
                write = recorder
            result = future.result()  # the callback runs only after completion
            write(engine, config_hash, prompt_version, run_id, result,
                  served_ids=actual_ids, local_result=local_result, source_input_id=source_input_id)
        except Exception as exc:
            # Remote/driver exception strings can contain sensitive values.
            log(f"Decisions comparison audit unavailable ({type(exc).__name__})")

    def completed(future):
        # add_done_callback executes inline for an already-completed Future.
        # Dispatch persistence too, so a fast response cannot block on SQL.
        try:
            _AUDIT_POOL.submit(persist, future)
        except Exception as exc:
            log(f"Decisions comparison audit unavailable ({type(exc).__name__})")

    job.add_done_callback(completed)
