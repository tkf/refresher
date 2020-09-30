import dataclasses
from contextlib import asynccontextmanager
from logging import getLogger
from math import inf
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import trio
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent

logger = getLogger(__name__)


@dataclasses.dataclass
class Some:
    value: Any


async def tryreceive(channel: trio.MemoryReceiveChannel) -> Optional[Some]:
    try:
        return Some(await channel.receive())
    except trio.ClosedResourceError:
        return None


@dataclasses.dataclass
class ReloadRequest:
    path: str


class EventTranslator(FileSystemEventHandler):
    def __init__(self, file_event_sender):
        self.file_event_sender = file_event_sender
        self.trio_token = trio.lowlevel.current_trio_token()

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent):
            trio.from_thread.run(
                self.file_event_sender.send, event, trio_token=self.trio_token
            )


@dataclasses.dataclass
class PageNotFound(Exception):
    filepath: Path

    def __str__(self):
        return f"File not found: {self.filepath}"


@dataclasses.dataclass
class Page:
    filepath: Path
    content: bytes = dataclasses.field(repr=False)
    is_cached: bool = False

    def is_html(self):
        return self.filepath.suffix.lower() in (".html", ".htm")


@dataclasses.dataclass
class Watcher:
    root: Path
    reload_receiver: trio.MemoryReceiveChannel

    def __post_init__(self):
        self.cache = {}

    async def get_request(self):
        return await self.reload_receiver.receive()

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
    reload_sender, reload_receiver = trio.open_memory_channel(inf)

    event_handler = EventTranslator(file_event_sender)
    observer = Observer()
    observer.schedule(event_handler, root, recursive=True)
    observer.start()

    async with trio.open_nursery() as nursery, file_event_receiver, reload_sender:
        try:
            nursery.start_soon(watcher_loop, file_event_receiver, reload_sender)
            yield Watcher(root=Path(root), reload_receiver=reload_receiver)
        finally:
            observer.stop()
            observer.join(3)


async def watcher_loop(
    file_event_receiver: "trio.MemoryReceiveChannel",
    reload_sender: "trio.MemorySendChannel",
) -> None:
    delay = 0.1

    if (ans := await tryreceive(file_event_receiver)) is None:
        return
    event: "FileSystemEvent" = ans.value
    while True:
        next_event: "Optional[FileSystemEvent]" = None
        with trio.move_on_after(delay):
            if (ans := await tryreceive(file_event_receiver)) is None:
                return
            next_event = ans.value
        if next_event is not None:
            event = next_event
            logger.debug("Got `%r` before %r seconds. Postpone reload...", event, delay)
            continue

        logger.debug(
            "No file changes happened within delay=%r seconds. Requesting reload...",
            delay,
        )
        req = ReloadRequest(event.src_path)
        try:
            await reload_sender.send(req)
        except trio.ClosedResourceError:
            return

        if (ans := await tryreceive(file_event_receiver)) is None:
            return
        event = ans.value
