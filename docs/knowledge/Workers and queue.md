# Workers and queue

The Celery app, the core task functions, and the headless batch runner.

## How it works
- Celery app (eager in-memory broker by default): `workers/celery_app.py`.
- Core task functions `detect_references` and `inject_links` (the heavy detection + injection work): `workers/tasks.py`.
- Headless multi-document batch run: `workers/batch_runner.py` — `python -m hyperlink_engine.workers.batch_runner --input … --output …`.
- Result/extractor cache: `workers/cache.py`.

## Gotchas
- Redis / a Celery worker are not required for a basic run — the default broker is in-memory and eager, so tasks run inline.

## Related
[[Orchestration and agents]] · [[Detection cascade]] · [[Running the app]] · [[_Home]]
