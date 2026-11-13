"""CMI Shipping Quoter - local web app.

Run:  python app.py      (then open http://127.0.0.1:5050)

Environment variables:
  QUOTER_HOST            interface to bind (default 127.0.0.1 = this PC only)
  QUOTER_PORT            port (default 5050)
  QUOTER_NO_BROWSER=1    don't auto-open the browser on start
  QUOTER_SETTINGS_FILE   path to the settings JSON (default data/settings.json)
"""

from __future__ import annotations

import os
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request, send_from_directory

from quoter import settings as settings_store
from quoter.carriers import CARRIERS, CarrierError
from quoter.models import QuoteError, QuoteRequest

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def create_app() -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    local_only = os.environ.get("QUOTER_HOST", "127.0.0.1") in ("127.0.0.1", "localhost")

    @app.before_request
    def block_foreign_hosts():
        # When bound to this PC only, refuse requests whose Host header isn't
        # local (protects the settings API from DNS-rebinding web pages).
        if local_only and request.host.split(":")[0] not in ("127.0.0.1", "localhost"):
            return jsonify({"error": "Forbidden host."}), 403

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/settings")
    def settings_page():
        return send_from_directory(STATIC_DIR, "settings.html")

    # ----- settings API --------------------------------------------------
    @app.get("/api/settings")
    def get_settings():
        current = settings_store.load()
        view = settings_store.public_view(current)
        view["status"] = {
            name: {"missing": cls(current["carriers"][name]).missing_fields()}
            for name, cls in CARRIERS.items()
        }
        return jsonify(view)

    @app.put("/api/settings")
    def put_settings():
        incoming = request.get_json(silent=True) or {}
        updated = settings_store.apply_update(settings_store.load(), incoming)
        settings_store.save(updated)
        return jsonify({"ok": True, "settings": settings_store.public_view(updated)})

    @app.post("/api/carriers/<name>/test")
    def test_carrier(name: str):
        cls = CARRIERS.get(name)
        if not cls:
            return jsonify({"ok": False, "error": f"Unknown carrier '{name}'."}), 404
        config = settings_store.load()["carriers"][name]
        try:
            message = cls(config).test_connection()
        except QuoteError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 200
        return jsonify({"ok": True, "message": message})

    # ----- quotes --------------------------------------------------------
    @app.get("/api/carriers")
    def list_carriers():
        current = settings_store.load()
        return jsonify([
            {
                "name": name,
                "display_name": cls.display_name,
                "enabled": bool(current["carriers"][name].get("enabled")),
                "environment": current["carriers"][name].get("environment"),
                "configured": not cls(current["carriers"][name]).missing_fields(),
            }
            for name, cls in CARRIERS.items()
        ])

    @app.post("/api/quote")
    def quote():
        data = request.get_json(silent=True) or {}
        current = settings_store.load()
        try:
            if not data.get("origin") or not str(data["origin"].get("postal_code", "")).strip():
                data["origin"] = current["origin"]
            req = QuoteRequest.from_dict(data)
        except QuoteError as exc:
            return jsonify({"error": str(exc)}), 400

        wanted = data.get("carriers") or [
            n for n in CARRIERS if current["carriers"][n].get("enabled")
        ]
        wanted = [n for n in wanted if n in CARRIERS]
        if not wanted:
            return jsonify({"error": "No carriers are enabled. Turn one on in Settings."}), 400

        def run(name: str):
            carrier = CARRIERS[name](current["carriers"][name])
            try:
                return name, [r.to_dict() for r in carrier.get_rates(req)], None
            except CarrierError as exc:
                return name, [], str(exc)
            except Exception as exc:  # never let one carrier break the page
                app.logger.exception("%s rating failed", name)
                return name, [], f"{carrier.display_name}: unexpected error ({exc.__class__.__name__})."

        rates, errors = [], {}
        with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
            for name, carrier_rates, error in pool.map(run, wanted):
                rates.extend(carrier_rates)
                if error:
                    errors[name] = error
        rates.sort(key=lambda r: r["total"])
        return jsonify({"rates": rates, "errors": errors})

    return app


def main() -> None:
    host = os.environ.get("QUOTER_HOST", "127.0.0.1")
    port = int(os.environ.get("QUOTER_PORT", "5050"))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}"
    app = create_app()

    if os.environ.get("QUOTER_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"\n  CMI Shipping Quoter running at {url}\n  Press Ctrl+C to stop.\n")
    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=port)
    else:
        serve(app, host=host, port=port)


if __name__ == "__main__":
    main()
