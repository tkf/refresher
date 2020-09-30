from typing import Any

class FileSystemEvent:
    src_path: str

class FileModifiedEvent(FileSystemEvent): ...

FileSystemEventHandler = Any
