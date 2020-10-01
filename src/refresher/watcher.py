import dataclasses
from contextlib import asynccontextmanager
from logging import getLogger
from math import inf
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

import trio
from watchdog.events import EVENT_TYPE_DELETED, EVENT_TYPE_MOVED

from .trio_watchdog import open_file_events

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent

logger = getLogger(__name__)


@dataclasses.dataclass
class Some:
    value: Any


async def trynext(aiter) -> Optional[Some]:
    try:
        async for x in aiter:
            return Some(x)
    except trio.ClosedResourceError:
        pass
    return None


@dataclasses.dataclass
class PageNotFound(Exception):
    filepath: Path

    def __str__(self):
        return f"File not found: {self.filepath}"


def is_html(path: Union[Path, str]) -> bool:
    return Path(path).suffix.lower() in (".html", ".htm")


@dataclasses.dataclass
class Page:
    filepath: Path
    content: bytes = dataclasses.field(repr=False)
    is_cached: bool = False

    @property
    def is_html(self):
        return is_html(self.filepath)


@dataclasses.dataclass
class Watcher:
    root: Path
    reload_receiver: trio.MemoryReceiveChannel

    def __post_init__(self):
        self.cache = {}

    def invalidate_page(self, pagepath: str):
        self.cache.pop(pagepath, None)

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
async def open_watcher(root: str):
    reload_sender, reload_receiver = trio.open_memory_channel(inf)

    # fmt: off
    async with trio.open_nursery() as nursery, \
            open_file_events(root) as file_event_receiver, \
            reload_sender:
        nursery.start_soon(watcher_loop, file_event_receiver, reload_sender)
        yield Watcher(root=Path(root), reload_receiver=reload_receiver)
    # fmt: on


class ReloadRequest:
    path: str

    def __init__(self, path: str):
        self.path = path
        self.updated = [path]

    def add_path(self, path: str):
        if path not in self.updated:
            self.updated.append(path)
        if self.path is None or is_html(path):
            # Latest HTML path; if not HTML files are updated, latest
            # path of any file type:
            self.path = path

    def add_event(self, event: "FileSystemEvent"):
        self.add_path(event_path(event))

    @classmethod
    def from_event(cls, event: "FileSystemEvent") -> "ReloadRequest":
        return cls(event_path(event))

    def __repr__(self):
        return f"<{type(self).__name__}: {self.path!r}>"


def event_path(event: "FileSystemEvent"):
    if event.event_type == EVENT_TYPE_MOVED:
        return event.dest_path
    else:
        # Created or modified
        return event.src_path


async def watcher_loop(
    file_event_receiver: "trio.MemoryReceiveChannel",
    reload_sender: "trio.MemorySendChannel",
) -> None:
    delay = 0.1

    filtered_events = (
        x async for x in file_event_receiver if x.event_type != EVENT_TYPE_DELETED
    )

    if (ans := await trynext(filtered_events)) is None:
        return
    req: ReloadRequest = ReloadRequest.from_event(ans.value)

    while True:
        next_event: "Optional[FileSystemEvent]" = None
        with trio.move_on_after(delay):
            if (ans := await trynext(filtered_events)) is None:
                return
            next_event = ans.value
        if next_event is not None:
            req.add_event(next_event)
            logger.debug(
                "Got `%r` before %r seconds. Postpone reload...", next_event, delay
            )
            continue

        logger.debug(
            "No file changes happened within delay=%r seconds. Requesting reload...",
            delay,
        )
        try:
            await reload_sender.send(req)
        except trio.ClosedResourceError:
            return

        if (ans := await trynext(filtered_events)) is None:
            return
        req = ReloadRequest.from_event(ans.value)
