"""Approved loopback WSGI entrypoint for the existing main application."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app


def main():
    from waitress import serve
    app.debug = False
    # Only the path-limited local upload gateway forwards HTTPS requests.
    # Never trust client-supplied Forwarded-For/Host or bind a public interface.
    serve(app, host='127.0.0.1', port=5000, threads=8,
          trusted_proxy='127.0.0.1', trusted_proxy_headers={'x-forwarded-proto'},
          clear_untrusted_proxy_headers=True, max_request_body_size=6 * 1024 * 1024,
          max_request_header_size=16384, channel_timeout=60, connection_limit=64,
          expose_tracebacks=False, ident='SmartBoarding')


if __name__ == '__main__':
    main()
