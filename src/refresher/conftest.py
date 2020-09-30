import dataclasses
from pathlib import Path
from typing import Final

import pytest
import quart

from .server import app
from .watcher import open_watcher


@dataclasses.dataclass
class RefresherTester:
    app: quart.Quart
    root: Path


DEFAULT_INDEX_HTML_BODY: Final[str] = "<body>hello"
DEFAULT_INDEX_HTML: Final[str] = "<html>" + DEFAULT_INDEX_HTML_BODY


@pytest.fixture
async def refresher(tmp_path):
    root = tmp_path
    del tmp_path

    (root / "index.html").write_text(DEFAULT_INDEX_HTML)

    async with open_watcher(str(root)) as watcher:
        app.config["REFRESHER_WATCHER"] = watcher
        yield RefresherTester(app, root)
