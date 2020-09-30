import json
import re
from math import inf
from pathlib import Path

import trio
from hypercorn.config import Config
from hypercorn.trio import serve
from quart import websocket
from quart_trio import QuartTrio
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

app = QuartTrio(__name__)
# TODO: ASGI app


@app.websocket("/livereload")
async def livereload_websocket():
    receive_channel = app.config["REFRESHER_RELOAD_RECEIVE_CHANNEL"]
    data = await websocket.receive()
    app.logger.debug(f"livereload_websocket: {data =}")
    handshake_reply = {
        "command": "hello",
        "protocols": ["http://livereload.com/protocols/official-7"],
        "serverName": "refresher",
    }
    await websocket.send(json.dumps(handshake_reply))
    while True:
        event = await receive_channel.receive()
        if not isinstance(event, FileModifiedEvent):
            continue
        reload_request = {
            "command": "reload",
            "path": event.src_path,
            "liveCSS": True,
        }
        app.logger.debug(f"file event: %r", event)
        app.logger.debug(f"sending reload request: %r", reload_request)
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


def inject_livereload_js(content, port=8000):
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
    return inject_livereload_js(content)


class EventTranslator(FileSystemEventHandler):
    def __init__(self, send_channel):
        self.send_channel = send_channel
        self.trio_token = trio.lowlevel.current_trio_token()

    def on_any_event(self, event):
        trio.from_thread.run(self.send_channel.send, event, trio_token=self.trio_token)


async def start_server(root=".", debug=True, port=8000):
    send_channel, receive_channel = trio.open_memory_channel(inf)

    app.config["REFRESHER_RELOAD_RECEIVE_CHANNEL"] = receive_channel
    app.config["REFRESHER_ROOT"] = Path(root)
    app.config["DEBUG"] = debug

    cfg = Config()
    cfg.bind = f"localhost:{port}"
    cfg.debug = debug

    event_handler = EventTranslator(send_channel)
    observer = Observer()
    observer.schedule(event_handler, root, recursive=True)
    observer.start()

    try:
        async with trio.open_nursery() as nursery:
            # https://pgjones.gitlab.io/hypercorn/how_to_guides/api_usage.html
            nursery.start_soon(serve, app, cfg)
    finally:
        observer.stop()
        observer.join(3)
