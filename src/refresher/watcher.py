import dataclasses
from contextlib import asynccontextmanager
from math import inf

import trio
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer


@dataclasses.dataclass
class ReloadRequest:
    path: str


class EventTranslator(FileSystemEventHandler):
    def __init__(self, send_channel):
        self.send_channel = send_channel
        self.trio_token = trio.lowlevel.current_trio_token()

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent):
            req = ReloadRequest(event.src_path)
            trio.from_thread.run(
                self.send_channel.send, req, trio_token=self.trio_token
            )


@dataclasses.dataclass
class Watcher:
    receive_channel: trio.MemoryReceiveChannel


@asynccontextmanager
async def open_watcher(path):
    send_channel, receive_channel = trio.open_memory_channel(inf)

    event_handler = EventTranslator(send_channel)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()

    try:
        yield Watcher(receive_channel=receive_channel)
    finally:
        observer.stop()
        observer.join(3)
