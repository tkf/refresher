import dataclasses
from contextlib import asynccontextmanager
from math import inf
from pathlib import Path

import trio
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer


@dataclasses.dataclass
class ReloadRequest:
    path: str


class EventTranslator(FileSystemEventHandler):
    def __init__(self, file_event_sender):
        self.file_event_sender = file_event_sender
        self.trio_token = trio.lowlevel.current_trio_token()

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent):
            req = ReloadRequest(event.src_path)
            trio.from_thread.run(
                self.file_event_sender.send, req, trio_token=self.trio_token
            )


@dataclasses.dataclass
class PageNotFound(Exception):
    filepath: Path

    def __str__(self):
        return f"File not found: {self.filepath}"


@dataclasses.dataclass
class Page:
    filepath: Path
    content: bytes
    is_cached: bool = False

    def is_html(self):
        return self.filepath.suffix.lower() in (".html", ".htm")


@dataclasses.dataclass
class Watcher:
    root: Path
    file_event_receiver: trio.MemoryReceiveChannel

    def __post_init__(self):
        self.cache = {}

    async def get_request(self):
        return await self.file_event_receiver.receive()

    async def get_page(self, pagepath: str):
        parts = list(pagepath.split("/"))
        if parts[-1] == "":
            parts[-1] = "index.html"  # FIXME
        filepath = self.root.joinpath(*parts)
        if not filepath.is_file():
            old = self.cache.get(pagepath, None)
            if old is None:
                raise PageNotFound(filepath)
            else:
                # TODO: invalidation (check last accessed time?)
                return dataclasses.replace(old, is_cached=True)
        content = filepath.read_bytes()
        page = Page(filepath=filepath, content=content)
        self.cache[pagepath] = page
        return page


@asynccontextmanager
async def open_watcher(root: Path):
    file_event_sender, file_event_receiver = trio.open_memory_channel(inf)

    event_handler = EventTranslator(file_event_sender)
    observer = Observer()
    observer.schedule(event_handler, root, recursive=True)
    observer.start()

    try:
        yield Watcher(root=Path(root), file_event_receiver=file_event_receiver)
    finally:
        observer.stop()
        observer.join(3)
