import os
from pathlib import Path
from typing import Union


def abspath(path: Union[os.PathLike, str]) -> Path:
    return Path(os.path.abspath(str(Path(path))))
