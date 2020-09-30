import json
import re
from logging import getLogger
from pathlib import Path

from hypercorn.config import Config
from hypercorn.trio import serve
from quart import websocket
from quart_trio import QuartTrio

from .watcher import PageNotFound, Watcher, open_watcher

app = QuartTrio(__name__)
# TODO: ASGI app

logger = getLogger(__name__)


@app.websocket("/livereload")
async def livereload_websocket():
    watcher = app.config["REFRESHER_WATCHER"]

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
        logger.debug("reload request: %r", req)
        await websocket.send(json.dumps(reload_request))


@app.route("/livereload.js")
async def livereload_js():
    with open(Path(__file__).parent / "assets" / "livereload.js") as file:
        return file.read()


html_tag_re = re.compile(b"<html[^>]*>", re.IGNORECASE)

script_livereload_js = """
<script>document.write('<script src="http://'
    + location.host.split(':')[0]
    + ':{port}/livereload.js"></'
    + 'script>')</script>
"""


def inject_livereload_js(content, port):
    scr = script_livereload_js.format(port=port).encode("ascii")
    m = html_tag_re.search(content)
    if not m:
        return scr + content  # FIXME
    i = m.end()
    return content[:i] + scr + content[i:]


@app.route("/", defaults={"pagepath": ""})
@app.route("/<path:pagepath>")
async def serve_file(pagepath):
    watcher: Watcher = app.config["REFRESHER_WATCHER"]
    try:
        page = await watcher.get_page(pagepath)
    except PageNotFound as err:
        logger.debug("%s", err)
        return f"Not Found: {pagepath}", 404
    if page.is_cached:
        logger.debug("Serving cached page: %s", pagepath)
    if page.is_html:
        port = app.config["REFRESHER_PORT"]  # FIXME
        return inject_livereload_js(page.content, port)
    else:
        return page.content


async def start_server(root, debug, port):
    app.config["REFRESHER_PORT"] = port
    app.config["DEBUG"] = debug

    cfg = Config()
    cfg.bind = f"localhost:{port}"
    cfg.debug = debug

    async with open_watcher(root) as watcher:
        app.config["REFRESHER_WATCHER"] = watcher

        # https://pgjones.gitlab.io/hypercorn/how_to_guides/api_usage.html
        await serve(app, cfg)
