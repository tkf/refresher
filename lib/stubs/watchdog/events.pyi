from typing import Any

EVENT_TYPE_MOVED: str
EVENT_TYPE_DELETED: str
EVENT_TYPE_CREATED: str
EVENT_TYPE_MODIFIED: str

class FileSystemEvent:
    src_path: str
    dest_path: str
    event_type: str

class FileModifiedEvent(FileSystemEvent): ...

FileSystemEventHandler = Any
