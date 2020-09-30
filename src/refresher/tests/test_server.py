from ..server import app

# See also:
# https://pgjones.gitlab.io/quart/how_to_guides/testing.html


async def test_livereload_js():
    test_client = app.test_client()
    response = await test_client.get("/livereload.js")
    assert response.status_code == 200
    result = await response.get_data()
    assert result.startswith(b"(function()")
    assert b"livereload" in result
