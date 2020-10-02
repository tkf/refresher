import os
from pathlib import Path
from typing import Union


class ApplicationError(RuntimeError):
    pass


def abspath(path: Union[os.PathLike, str]) -> Path:
    return Path(os.path.abspath(str(Path(path))))
