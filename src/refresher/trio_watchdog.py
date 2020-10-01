from contextlib import asynccontextmanager
from math import inf

import trio
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class EventTranslator(FileSystemEventHandler):
    def __init__(self, file_event_sender):
        self.file_event_sender = file_event_sender
        self.trio_token = trio.lowlevel.current_trio_token()

    def on_any_event(self, event):
        trio.from_thread.run(
            self.file_event_sender.send, event, trio_token=self.trio_token
        )
        # See:
        # * https://python-watchdog.readthedocs.io


@asynccontextmanager
async def open_file_events(root: str):
    file_event_sender, file_event_receiver = trio.open_memory_channel(inf)

    event_handler = EventTranslator(file_event_sender)
    observer = Observer()
    observer.schedule(event_handler, root, recursive=True)
    observer.start()

    async with file_event_sender, file_event_receiver:
        try:
            yield file_event_receiver
        finally:
            observer.stop()
            observer.join(3)
