from contextlib import asynccontextmanager
from logging import getLogger
from math import inf
from pathlib import Path
from typing import Sequence, Union

import trio
from watchdog.events import (
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DELETED,
    EVENT_TYPE_MOVED,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from .utils import abspath

logger = getLogger(__name__)


class RootRecreated:
    is_directory: bool = True
    event_type: str = EVENT_TYPE_CREATED
    dest_path: str

    def __init__(self, src_path: str):
        self.src_path: str = src_path


GenericEvent = Union[FileSystemEvent, RootRecreated]


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
async def open_raw_file_events(root: Path, *, recursive: bool):
    logger.debug("open_raw_file_events(%r, recursive=%r)", root, recursive)
    file_event_sender, file_event_receiver = trio.open_memory_channel(inf)

    event_handler = EventTranslator(file_event_sender)
    observer = Observer()
    observer.schedule(event_handler, str(root), recursive=recursive)
    observer.start()

    try:
        async with file_event_sender, file_event_receiver:
            try:
                yield file_event_receiver
            finally:
                t0 = trio.current_time()
                stop_success = False
                try:
                    with trio.move_on_after(4) as cleanup_scope:
                        cleanup_scope.shield = True
                        await trio.to_thread.run_sync(observer.stop)
                        await trio.to_thread.run_sync(observer.join, 3)
                        stop_success = True
                finally:
                    duration = trio.current_time() - t0
                    logger.debug(
                        "cleanup_scope.cancel_called = %r", cleanup_scope.cancel_called
                    )
                    if stop_success:
                        logger.debug("Stopping observer took %s seconds.", duration)
                    else:
                        logger.debug(
                            "Stopping observer did not finish in %s seconds.", duration
                        )
    finally:
        logger.debug(
            "FINISHING: open_raw_file_events(%r, recursive=%r)", root, recursive
        )


async def recursive_restart(async_fn, paths: Sequence[Path]):
    rest = list(paths)
    if not rest:
        await async_fn()
        return
    front = rest.pop(0)

    async with open_raw_file_events(front.parent, recursive=False) as receiver:

        async def recurse():
            async with trio.open_nursery() as nursery:
                nursery.start_soon(recursive_restart, async_fn, rest)
                async for event in receiver:
                    logger.debug("%r -> %r", front, event)
                    if (
                        event.event_type == EVENT_TYPE_DELETED
                        and Path(event.src_path) == front
                    ):
                        break
                t0 = trio.current_time()
                logger.info("`%s` deleted. Stopping watchers...", front)
                nursery.cancel_scope.cancel()
            duration = trio.current_time() - t0
            logger.info(
                "`%s` deleted. Stopping watchers...DONE (took %s seconds)",
                front,
                duration,
            )

        await recurse()
        num_errors = 0
        while True:
            logger.info("Waiting for `%s` to be recreated.", front)
            async for event in receiver:
                if event.event_type == EVENT_TYPE_DELETED:
                    continue
                elif event.event_type == EVENT_TYPE_MOVED:
                    name = event.dest_path
                else:
                    name = event.src_path
                if front.parent / name == front:
                    if not front.is_dir():
                        logger.info("Not a directory: %s", front)
                        continue
                    break

            logger.info("New directory recreated at: %s", front)
            try:
                await recurse()
                num_errors = 0
            except Exception as err:  # TODO: narrower exception
                num_errors += 1
                if num_errors >= 10:
                    raise
                logger.error("Ignoring an error while watching %s: %r", front, err)


@asynccontextmanager
async def open_file_events(root: Path):
    root = abspath(root)

    paths = list(root.parents)
    paths.reverse()
    paths.pop(0)  # remove Path("/")
    paths.append(root)

    file_event_sender, file_event_receiver = trio.open_memory_channel(inf)
    isfirst = True

    async def true_watcher():
        nonlocal isfirst
        if not isfirst:
            await file_event_sender.send(RootRecreated(str(root)))
        isfirst = False

        async with open_raw_file_events(root, recursive=True) as receiver:
            async for event in receiver:
                logger.debug("SEND: %r", event)
                await file_event_sender.send(event)

    async with trio.open_nursery() as nursery, file_event_sender, file_event_receiver:
        nursery.start_soon(recursive_restart, true_watcher, paths)
        yield file_event_receiver
        nursery.cancel_scope.cancel()
