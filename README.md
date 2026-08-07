# Chanina

**Chanina** is a decorator-based API for running Playwright browser automation as scalable
Celery tasks. You write plain functions ("libretti") decorated with `@app.libretto(...)`;
Chanina takes care of the browser lifecycle and hands each task an isolated browser session.

---

## Features

- **Shared Chromium across workers**: with the default `browser_engine="chromium"`, a single
  Chromium instance is supervised as its own subprocess and shared by every worker process over
  CDP. Each task still gets its own isolated `BrowserContext`, but you're not paying for one
  browser per worker process.
- **Firefox, one per worker process**: `browser_engine="firefox"` launches a local Firefox for
  each worker process instead (Playwright has no way to share a Firefox instance across
  processes the way it does for Chromium over CDP).
- **Persistent browser profiles**: pass `profile_dir` to keep history/cookies/cache/extensions
  on disk across restarts, for either engine.
- **Celery-based task system**: every libretto is a real Celery task — use `bind=True` and any
  other Celery task option you'd normally use.
- **CLI**: run a worker, or dispatch a single libretto, from the terminal.
- **Crash instead of silently degrading**: if the browser can't be recovered (the shared
  Chromium subprocess fails to restart, or a worker exhausts its reconnect attempts against
  either engine), the worker process is killed outright instead of carrying on without a working
  browser — see [Crashing on an unrecoverable browser](#crashing-on-an-unrecoverable-browser).

---

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install chanina
```

or

```bash
poetry new my-chanina-project
cd my-chanina-project
poetry add chanina
poetry install
```

Playwright needs its browsers installed separately:

```bash
poetry run playwright install chromium firefox
```

---

## Usage

### Define an app

```python
# myapp.py
from chanina import ChaninaApplication

app = ChaninaApplication(
    __file__,
    browser_engine="chromium",       # or "firefox"
    headless=True,
    backend="redis://localhost:6379/0",
    broker="redis://localhost:6379/0",
)
```

### Write a libretto

```python
@app.libretto("visit_page")
def visit_page(session, args: dict):
    # `session` is a WorkerSession wrapping an isolated playwright BrowserContext,
    # created fresh for this task and closed automatically once it returns.
    page = session.new_page()
    page.goto(args["url"])
    title = page.title()
    return title
```

The first parameter of a libretto function is always the session, and the last is always the
`args` dict the task was invoked with. If you use Celery's `bind=True`, the bound task instance
comes first instead, before the session:

```python
@app.libretto("visit_page", bind=True)
def visit_page(self, session, args: dict):
    ...
```

### Run a worker

```bash
poetry run python -m chanina --app myapp:app --celery loglevel=info concurrency=4
```

Everything after `--celery`/`-c` is forwarded to Celery: a `key=value` token becomes
`--key=value`, and a bare token with no `=` (e.g. `without-mingle`) becomes a no-argument flag
(`--without-mingle`) — for Celery options like `--without-mingle`, `--without-gossip`, or
`--without-heartbeat` that don't take a value:

```bash
poetry run python -m chanina --app myapp:app \
    --celery without-mingle without-gossip without-heartbeat concurrency=4
```

### Dispatch a task

From your own script, once a worker is running:

```python
from myapp import app

# Keyword arguments passed to apply_async become the task's `args` dict.
app.libretti["visit_page"].task.apply_async(kwargs={"url": "https://example.com"})
```

Or without writing a dispatch script, straight from the CLI (still requires a worker consuming
the queue to actually run it):

```bash
poetry run python -m chanina --app myapp:app --libretto visit_page --config url=https://example.com
```

(`--libretto`/`-l` defaults to the built-in `chanina.list_libretti`, which just logs every
registered libretto — useful as a sanity check that your app loads correctly.)

---

## Persistent browser profiles

```python
import os

app = ChaninaApplication(
    __file__,
    browser_engine="chromium",
    profile_dir=os.environ.get("CHANINA_PROFILE_DIR"),
    ...
)
```

With a profile set, tasks stop getting an isolated context each — a fresh context wouldn't see
the profile's cookies/storage anyway, so every task reuses the profile's own persistent context
instead (concurrently, if several tasks run at once). Without a profile, contexts stay isolated
per task as usual.

`profile_dir` is treated as a read-only template, never handed to the browser directly: if it
already holds a profile, chanina copies it into a disposable directory under the system temp dir
before launching, and deletes that copy again on shutdown. This keeps the template reusable
across restarts and immune to being corrupted by a crashed run. If `profile_dir` doesn't exist
yet, it's created and used as-is, becoming the template for next time.

- **Chromium**: since there's only ever one shared instance, this has no concurrency caveats.
- **Firefox**: a given profile directory can only be opened by one running Firefox at a time, so
  `python -m chanina --celery ...` forces `concurrency=1` whenever `browser_engine="firefox"` is
  used, regardless of what's passed.

---

## Crashing on an unrecoverable browser

By default (`crash_on_browser_failure=True`, the default on `ChaninaApplication`), chanina kills
the worker process outright — `SIGKILL`, no graceful shutdown — instead of carrying on without a
working browser:

- **Chromium**: the main process's `BrowserSupervisor` monitor thread checks the shared
  subprocess is alive every `monitor_interval` seconds; if a restart attempt fails, it kills the
  main (Celery) process immediately.
- **Both engines**: when a worker process can't get a browser handle for a task — the shared
  Chromium is unreachable, or its own local Firefox is dead — it retries a few times and, if that
  still fails, kills both itself and its parent (the main Celery process).

This is meant for deployments where a process supervisor (a Kubernetes `restartPolicy`, for
example) relaunches the whole worker from scratch whenever it exits — a hard, unmistakable death
gets that restart, where a silently degraded worker (still running, still picking up tasks, but
failing every one of them because it has no browser) wouldn't.

Set `crash_on_browser_failure=False` to go back to the old behavior of only failing the affected
task(s) and letting the worker keep retrying on its own:

```python
app = ChaninaApplication(
    __file__,
    crash_on_browser_failure=False,
    ...
)
```

---

## Backward compatibility

Code written against the pre-1.0 API (a single `WorkerSession` per worker process, injected via
`browser_name`/`user_profile_path`) keeps working: `WorkerSession` is now a thin, deprecated
compatibility wrapper around the per-task `BrowserContext`, and `browser_name`/
`user_profile_path` are accepted as deprecated aliases for `browser_engine`/`profile_dir`. Using
any of these emits a `DeprecationWarning` pointing at the replacement.

---

## License

For now this project has no Licence, i'm working on it.
