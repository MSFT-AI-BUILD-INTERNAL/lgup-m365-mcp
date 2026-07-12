from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


@contextmanager
def temporary_env(**values: str) -> Iterator[None]:
    saved: dict[str, str | None] = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, previous in saved.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


class _JwksHandler(BaseHTTPRequestHandler):
    jwks_payload: bytes = b"{}"

    def do_GET(self):  # noqa: N802
        if self.path != "/keys":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.jwks_payload)))
        self.end_headers()
        self.wfile.write(self.jwks_payload)

    def log_message(self, format, *args):  # noqa: A003
        return


@contextmanager
def local_jwks_server(jwks: dict) -> Iterator[str]:
    payload = json.dumps(jwks).encode("utf-8")
    _JwksHandler.jwks_payload = payload
    server = ThreadingHTTPServer(("127.0.0.1", 0), _JwksHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/keys"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def build_signing_material() -> tuple[object, dict]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = str(uuid4())
    public_jwk["use"] = "sig"
    public_jwk["alg"] = "RS256"
    return private_key, {"keys": [public_jwk]}


def sign_token(private_key: object, claims: dict, kid: str) -> str:
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})
