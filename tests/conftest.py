import socket
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
import uvicorn

from guardbench.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "eval.sqlite3")


@contextmanager
def http_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("Test HTTP server did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
