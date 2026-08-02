"""
Visual demo of the shared-browser design: launch a Celery worker with
several child processes, dispatch multiple 'visual.visit_sentinelle' tasks,
and watch each task open its own page/window on the *same* underlying
Chromium instance (headless=False), all navigating to
https://www.equipe-sentinelle.fr.

Run from the repo root (two terminals):
    poetry run python -m chanina --app tests.visual_demo:app --celery loglevel=info concurrency=4
    poetry run python -m tests.dispatch_visual_demo
"""
import logging

from chanina import ChaninaApplication

app = ChaninaApplication(
    __file__,
    headless=False,
    browser_engine="chromium",
    backend="redis://localhost:6379/1",
    broker="redis://localhost:6379/1",
)


@app.libretto("visual.visit_sentinelle")
def visit_sentinelle(context, args: dict):
    visit_id = args.get("visit_id", "?")
    page = context.new_page()
    logging.info(f"[visit {visit_id}] opening https://www.equipe-sentinelle.fr")
    page.goto("https://www.equipe-sentinelle.fr")
    title = page.title()
    logging.info(f"[visit {visit_id}] loaded, title={title!r}, staying open 8s ...")
    page.wait_for_timeout(8000)
    return title
