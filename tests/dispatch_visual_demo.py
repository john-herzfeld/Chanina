"""
Dispatches a handful of 'visual.visit_sentinelle' tasks against the worker
started from tests/visual_demo.py, so several tasks run concurrently on the
shared browser.
"""
from tests.visual_demo import app

VISIT_COUNT = 4

if __name__ == "__main__":
    task = app.libretti["visual.visit_sentinelle"].task
    for visit_id in range(VISIT_COUNT):
        task.apply_async(kwargs={"visit_id": visit_id})
        print(f"dispatched visit {visit_id}")
