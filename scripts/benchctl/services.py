"""Auxiliary services some workloads depend on (declared with
`extra = { needs = ["nginx"] }` in bench.toml).

nginx is the *neutral* HTTP server used by the concurrency category's HTTP
client benchmark: written in neither language, pinned to its own cores, with a
static response so the clients are what is being measured.
"""

from __future__ import annotations

import contextlib
import http.client
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .util import SCRATCH_DIR, log

NGINX_PORT = 18090
# The same bytes the benchmark HTTP servers return for /users/42.
NGINX_BODY = ('{"id":42,"name":"user-42","email":"user-42@example.com","score":4493741490884227880,'
              '"tags":["alpha","beta","gamma"],"active":true}')

NGINX_CONF = """
worker_processes {workers};
worker_rlimit_nofile 20000;
pid {prefix}/nginx.pid;
error_log {prefix}/error.log warn;
daemon off;
events {{ worker_connections 20000; use epoll; multi_accept on; }}
http {{
    access_log off;
    keepalive_requests 100000000;
    keepalive_timeout 300s;
    client_body_temp_path {prefix}/tmp/body;
    proxy_temp_path {prefix}/tmp/proxy;
    fastcgi_temp_path {prefix}/tmp/fastcgi;
    uwsgi_temp_path {prefix}/tmp/uwsgi;
    scgi_temp_path {prefix}/tmp/scgi;
    server {{
        listen 127.0.0.1:{port} backlog=4096;
        location = /user {{
            default_type application/json;
            return 200 '{body}';
        }}
    }}
}}
"""


def _ready(port: int) -> bool:
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
        c.request("GET", "/user")
        ok = c.getresponse().status == 200
        c.close()
        return ok
    except OSError:
        return False


@contextlib.contextmanager
def nginx(cpus: str, workers: int, port: int = NGINX_PORT):
    exe = shutil.which("nginx") or "/usr/sbin/nginx"
    if not Path(exe).exists():
        raise FileNotFoundError("nginx not installed (run `make setup`)")
    prefix = SCRATCH_DIR / "nginx"
    (prefix / "tmp").mkdir(parents=True, exist_ok=True)
    conf = prefix / "nginx.conf"
    conf.write_text(NGINX_CONF.format(workers=workers, prefix=prefix, port=port, body=NGINX_BODY))
    proc = subprocess.Popen(["taskset", "-c", cpus, exe, "-c", str(conf), "-p", str(prefix)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, close_fds=True)
    try:
        deadline = time.monotonic() + 10
        while not _ready(port):
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"nginx failed to start: {proc.stderr.read().decode(errors='replace')}")
            time.sleep(0.01)
        log(f"nginx ready on 127.0.0.1:{port} (cores {cpus}, {workers} workers)")
        yield f"http://127.0.0.1:{port}/user"
    finally:
        proc.send_signal(signal.SIGQUIT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@contextlib.contextmanager
def for_workloads(spec, workloads):
    """Start every service the given workloads need; yields nothing useful."""
    needs = {n for w in workloads for n in w.extra.get("needs", [])}
    with contextlib.ExitStack() as stack:
        if "nginx" in needs:
            cpus = spec.cpus("nginx")
            stack.enter_context(nginx(cpus, workers=spec.ncpus("nginx")))
        yield
