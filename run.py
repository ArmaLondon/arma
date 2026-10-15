"""Arma CLI: run the agent team on the demo shop (or a local static site).

    uv run python run.py --demo --model sonnet [--chaos] [--until audit] [--resume]
"""

import argparse
import asyncio
import functools
import json
import shutil
import sys
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from arma.config import ROOT, load_env
from arma.events import PHASES, EventBus, load_events
from arma.orchestrator import BudgetExceeded, Orchestrator
from arma.state import Store

STATE = ROOT / "state"
DEMO_PORT = 8765


class NoCacheQuiet(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


def serve(directory: Path, port: int) -> ThreadingHTTPServer:
    """Serve on `port`, or the next free one if it is taken."""
    handler = functools.partial(NoCacheQuiet, directory=str(directory))
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), handler)
            break
        except OSError:
            continue
    else:
        raise OSError(f"no free port in {port}-{port + 19}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="copy demo-shop/ to runs/demo-shop/ and serve it")
    ap.add_argument("--site", type=Path, help="local static site (git repo) to remediate")
    ap.add_argument("--url", help="URL where --site is served")
    ap.add_argument("--resume", action="store_true", help="continue from state/state.json")
    ap.add_argument("--model", help="model alias, e.g. sonnet (default: SDK default)")
    ap.add_argument("--chaos", action="store_true", help="inject one transient audit_page failure")
    ap.add_argument("--budget", type=float, help="stop cleanly above this cost (USD)")
    ap.add_argument("--until", choices=PHASES, help="stop after this phase")
    args = ap.parse_args()
    load_env()

    STATE.mkdir(exist_ok=True)
    store = Store(STATE / "state.json", reset=not args.resume)
    meta = store.get("meta")
    srv = None
    if args.demo:
        site = ROOT / "runs" / "demo-shop"
        if not args.resume or not site.exists():
            shutil.rmtree(site, ignore_errors=True)
            shutil.copytree(ROOT / "demo-shop", site)
            for d in ("shots", "out"):
                shutil.rmtree(STATE / d, ignore_errors=True)
        srv = serve(site, DEMO_PORT)
        url = f"http://localhost:{srv.server_address[1]}/"
    elif args.site and args.url:
        site, url = args.site, args.url
    else:
        ap.error("use --demo, or --site with --url")

    # one recording per run; --resume keeps appending to it with a continuous clock
    rec = Path(meta["recording"]) if args.resume and meta.get("recording") else \
        ROOT / "recordings" / f"run-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    bus = EventBus(rec)
    if rec.exists() and args.resume:
        past = load_events(rec)
        if past:
            bus._t0 = time.monotonic() - past[-1]["t"] - 1
    store.set("meta", {**store.get("meta"), "recording": str(rec), "model": args.model or "default"})
    print(f"recording → {rec.relative_to(ROOT)}", file=sys.stderr)

    orch = Orchestrator(store=store, bus=bus, site_dir=site, base_url=url, work_dir=STATE,
                        model=args.model, chaos=args.chaos, budget=args.budget, until=args.until)
    started = time.monotonic()
    try:
        asyncio.run(orch.run())
    except BudgetExceeded as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted: continue with --resume", file=sys.stderr)
        return 130
    finally:
        if srv:
            srv.shutdown()
    print(json.dumps({"recording": str(rec.relative_to(ROOT)), "cost_usd": round(store.get("cost_usd"), 4),
                      "duration_s": round(time.monotonic() - started, 1),
                      "issues": len(store.issues()), "phases_done": store.get("phases_done")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
