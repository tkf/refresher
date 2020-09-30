import json
import re
from pathlib import Path

from hypercorn.config import Config
from hypercorn.trio import serve
from quart import websocket
from quart_trio import QuartTrio

from .watcher import open_watcher

app = QuartTrio(__name__)
# TODO: ASGI app


@app.websocket("/livereload")
async def livereload_websocket():
    watcher = app.config["REFRESHER_WATCHER"]
    data = await websocket.receive()
    app.logger.debug(f"livereload_websocket: {data =}")
    handshake_reply = {
        "command": "hello",
        "protocols": ["http://livereload.com/protocols/official-7"],
        "serverName": "refresher",
    }
    await websocket.send(json.dumps(handshake_reply))
    while True:
        req = await watcher.receive_channel.receive()
        reload_request = {
            "command": "reload",
            "path": req.path,
            "liveCSS": True,
        }
        app.logger.debug(f"reload request: %r", req)
        await websocket.send(json.dumps(reload_request))


@app.route("/livereload.js")
async def livereload_js():
    with open(Path(__file__).parent / "assets" / "livereload.js") as file:
        return file.read()


html_tag_re = re.compile("<html[^>]*>", re.IGNORECASE)

script_livereload_js = """
<script>document.write('<script src="http://'
    + location.host.split(':')[0]
    + ':{port}/livereload.js"></'
    + 'script>')</script>
"""


def inject_livereload_js(content, port):
    m = html_tag_re.search(content)
    if not m:
        return script_livereload_js.format(port=port) + content  # FIXME
    i = m.end()
    return content[:i] + script_livereload_js.format(port=port) + content[i:]


@app.route("/", defaults={"pagepath": ""})
@app.route("/<path:pagepath>")
async def serve_file(pagepath):
    parts = list(pagepath.split("/"))
    if parts[-1] == "":
        parts[-1] = "index.html"  # FIXME
    root = app.config["REFRESHER_ROOT"]
    filepath = root.joinpath(*parts)
    app.logger.debug(
        "pagepath = %s, parts = %r, filepath = %s", pagepath, parts, filepath
    )
    if not filepath.is_file():
        app.logger.debug("File not found: %s", filepath)
        return f"Not Found: {pagepath}", 404
    content = filepath.read_text()
    if filepath.suffix.lower() not in (".html", ".htm"):
        return content
    port = app.config["REFRESHER_PORT"]  # FIXME
    return inject_livereload_js(content, port)


async def start_server(root, debug, port):
    app.config["REFRESHER_PORT"] = port
    app.config["REFRESHER_ROOT"] = Path(root)
    app.config["DEBUG"] = debug

    cfg = Config()
    cfg.bind = f"localhost:{port}"
    cfg.debug = debug

    async with open_watcher(root) as watcher:
        app.config["REFRESHER_WATCHER"] = watcher

        # https://pgjones.gitlab.io/hypercorn/how_to_guides/api_usage.html
        await serve(app, cfg)
