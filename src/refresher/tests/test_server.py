import re

from ..conftest import DEFAULT_INDEX_HTML_BODY, RefresherTester
from ..server import app

# See also:
# * https://pgjones.gitlab.io/quart/how_to_guides/testing.html
# * https://pytest-trio.readthedocs.io


def assert_has_livereload_js(content: bytes):
    assert re.search(br"<script>.+/livereload\.js.+</script>", content, re.DOTALL)


async def test_livereload_js():
    test_client = app.test_client()
    response = await test_client.get("/livereload.js")
    assert response.status_code == 200
    result = await response.get_data()
    assert result.startswith(b"(function()")
    assert b"livereload" in result


async def test_cache(refresher: RefresherTester):
    app = refresher.app
    test_client = app.test_client()

    response0 = await test_client.get("/")
    result0: bytes = await response0.get_data()
    assert DEFAULT_INDEX_HTML_BODY in result0.decode()
    assert_has_livereload_js(result0)

    (refresher.root / "index.html").unlink()

    response1 = await test_client.get("/")
    result1: bytes = await response1.get_data()
    assert DEFAULT_INDEX_HTML_BODY in result1.decode()
    assert_has_livereload_js(result1)


async def test_notfound(refresher: RefresherTester):
    app = refresher.app
    test_client = app.test_client()

    response = await test_client.get("/NON/EXISTING/PAGE.html")
    assert response.status_code == 404
    result: bytes = await response.get_data()
    assert_has_livereload_js(result)
