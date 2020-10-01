import html
import json
import mimetypes
import re
from logging import getLogger
from pathlib import Path
from typing import NoReturn, Optional

from hypercorn.config import Config
from hypercorn.trio import serve
from quart import ResponseReturnValue, request, websocket
from quart_trio import QuartTrio

from .watcher import PageNotFound, Watcher, open_watcher

app = QuartTrio(__name__)
# TODO: ASGI app

logger = getLogger(__name__)


@app.websocket("/livereload")
async def livereload_websocket() -> NoReturn:
    watcher: Watcher = app.config["REFRESHER_WATCHER"]

    handshake_request = json.loads(await websocket.receive())
    logger.debug("handshake_request: %r", handshake_request)
    client_protocols = handshake_request.get("protocols", [])
    if "http://livereload.com/protocols/official-7" not in client_protocols:
        raise RuntimeError(f"Unsupported protocols: {client_protocols}")

    handshake_reply = {
        "command": "hello",
        "protocols": ["http://livereload.com/protocols/official-7"],
        "serverName": "refresher",
    }
    await websocket.send(json.dumps(handshake_reply))

    while True:
        req = await watcher.get_request()
        reload_request = {
            "command": "reload",
            "path": req.path,
            "liveCSS": True,
        }
        logger.info("Reloading: %s", req.path)
        logger.debug("req = %r", req)
        await websocket.send(json.dumps(reload_request))


@app.route("/livereload.js")
async def livereload_js() -> ResponseReturnValue:
    with open(Path(__file__).parent / "assets" / "livereload.js") as file:
        return file.read()


close_tag_re = re.compile(b"</(body|html)>", re.IGNORECASE)

script_livereload_js = """
<script>document.write('<script src="http://'
    + location.host.split(':')[0]
    + ':{port}/livereload.js"></'
    + 'script>')</script>
"""


def inject_livereload_js(content: bytes, port: int) -> bytes:
    scr = script_livereload_js.format(port=port).encode("ascii")
    m = close_tag_re.search(content)
    if not m:
        return content + scr
    i = m.start() - 1
    return content[:i] + scr + content[i:]


def notfound_page(pagepath: str, port: int) -> ResponseReturnValue:
    scr = script_livereload_js.format(port=port)
    return (
        f"<html>{scr}<body><h1>Not found: <code>/{html.escape(pagepath)}</code></h1>",
        404,
    )


host_port_re = re.compile(".*:([0-9]+)$")


def port_from_host(host: str) -> Optional[int]:
    m = host_port_re.match(host)
    if m:
        return int(m.group(1))
    return None


def current_port(request=request) -> int:
    port = port_from_host(request.host)
    if port is not None:
        return port
    if request.scheme == "https":
        return 443
    else:
        return 80


@app.route("/", defaults={"pagepath": ""})
@app.route("/<path:pagepath>")
async def serve_file(pagepath) -> ResponseReturnValue:
    watcher: Watcher = app.config["REFRESHER_WATCHER"]
    port = current_port()
    if request.cache_control.no_cache:
        # https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control
        logger.info("Invalidating page: %s", pagepath)
        watcher.invalidate_page(pagepath)
    try:
        page = await watcher.get_page(pagepath)
    except PageNotFound as err:
        logger.debug("%s", err)
        return notfound_page(pagepath, port)
    logger.debug("page = %r", page)
    if page.is_cached:
        logger.info("Serving cached page: %s", pagepath)
    if page.is_html:
        return inject_livereload_js(page.content, port)
    else:
        mime, encoding = mimetypes.guess_type(page.filepath)
        if not mime:
            mime, encoding = mimetypes.guess_type(pagepath)
        header = {}
        if mime:
            header["Content-Type"] = mime
        if encoding:
            header["Content-Encoding"] = encoding
        return page.content, 200, header


async def start_server(root: str, debug: bool, port: int) -> None:
    app.config["DEBUG"] = debug

    cfg = Config()
    cfg.bind = [f"localhost:{port}"]

    async with open_watcher(root) as watcher:
        app.config["REFRESHER_WATCHER"] = watcher
        logger.info("Serving and watching: %s", watcher.root.resolve())

        # https://pgjones.gitlab.io/hypercorn/how_to_guides/api_usage.html
        await serve(app, cfg)
