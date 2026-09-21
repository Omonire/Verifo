"""Single-process entrypoint: web app + embedded background worker (+ optional seed).

Runs the Flask application, the background queue worker thread, and (when
VERIFO_SEED=1) the seeder in ONE process. Replaces the old two-window setup
(run.py + `flask --app run.py run-worker`) for local use and for Render.

    python server.py                    # seed (if flagged) + worker + web app
    python server.py --worker-only      # only the queue worker (blocking)  [dedicated Render worker service]
    python server.py --port 8080        # override port
    gunicorn server:app                 # WSGI entry (no embedded worker)

Environment:
    VERIFO_SEED         "1" -> run seed_demo.run_seed() on boot (respects SEED_SAMPLE)
    VERIFO_EMBED_WORKER "0" -> skip the embedded worker thread
    VERIFO_KEEPALIVE    "0" -> disable the self-ping keepalive thread
    VERIFO_KEEPALIVE_INTERVAL  seconds between pings (default 240)
    VERIFO_PUBLIC_URL   public base URL for the keepalive (Render sets RENDER_EXTERNAL_URL)
    PORT / HOST         bind address for hosted platforms (Render sets PORT)
    FLASK_DEBUG         "1" -> debug/tracebacks (reloader stays OFF: the single
                              process owns the worker thread)
"""
import argparse
import signal
import threading

from app import create_app


def _flag(name: str, default: str = "0") -> bool:
    return os_env(name, default).strip().lower() in ("1", "true", "yes", "on")


def os_env(name: str, default: str = "") -> str:
    import os

    return os.environ.get(name, default)


def build_app():
    """Create the app, ensure tables exist, and seed if VERIFO_SEED=1."""
    app = create_app()
    with app.app_context():
        from app.extensions import db

        db.create_all()
        if _flag("VERIFO_SEED"):
            from seed_demo import run_seed

            result = run_seed()
            app.logger.info(
                "Seeded on boot (%s) org=%s", result["mode"], result["organization"])
    return app


app = build_app()


def start_embedded_worker():
    """Start the queue worker as a daemon thread (one process = web + worker)."""
    from app.services.worker import start_worker

    return start_worker(app)


def run_worker_blocking():
    """Block forever processing queue tasks (Windows-safe signal handling)."""
    from app.services.worker import worker_loop

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    worker_loop(app, stop_event=stop)


def start_keepalive():
    """Keep the instance awake on free Render by re-hitting its own public
    health endpoint every few minutes.

    Render's free tier sleeps a service after ~15 minutes of inactivity. While
    the instance is up, re-hitting its own public URL through the load balancer
    counts as inbound traffic, so the sleep timer never trips. Local/dev runs
    with no public URL simply skip this (self-ping would be pointless locally).
    """
    import os
    import time
    import urllib.request

    if not _flag("VERIFO_KEEPALIVE", "1"):
        return None
    base = (os.environ.get("RENDER_EXTERNAL_URL")
            or os.environ.get("VERIFO_PUBLIC_URL") or "").rstrip("/")
    if not base or "localhost" in base or "127.0.0.1" in base:
        return None
    interval = int(os.environ.get("VERIFO_KEEPALIVE_INTERVAL", "240"))
    target = base + "/api/v1/health"

    def ping_loop():
        while True:
            time.sleep(interval)
            try:
                with urllib.request.urlopen(target, timeout=20) as resp:
                    resp.read()
            except Exception as exc:
                app.logger.warning("keepalive ping failed: %s", exc)

    thread = threading.Thread(target=ping_loop, name="keepalive", daemon=True)
    thread.start()
    app.logger.info("Keepalive started -> %s every %ss", target, interval)
    return thread


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verifo unified entrypoint")
    parser.add_argument("--worker-only", action="store_true",
                        help="Run only the queue worker (blocking).")
    parser.add_argument("--host", default=None, help="Bind host (default: PORT set -> 0.0.0.0, else 127.0.0.1).")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: PORT env or 5000).")
    parser.add_argument("--debug", action="store_true", default=None,
                        help="Force debug mode (default: FLASK_DEBUG env).")
    args = parser.parse_args(argv)

    if args.worker_only:
        run_worker_blocking()
        return

    if _flag("VERIFO_EMBED_WORKER", "1"):
        start_embedded_worker()
        app.logger.info("Embedded queue worker started (thread).")

    start_keepalive()

    host = args.host or os_env("HOST") or (
        "0.0.0.0" if os_env("PORT") else "127.0.0.1")
    port = args.port or int(os_env("PORT") or 5000)
    debug = _flag("FLASK_DEBUG", "0") if args.debug is None else args.debug
    # use_reloader=False: this process owns the worker thread, so web and worker
    # must stay in the same process (the reloader would split them again).
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()