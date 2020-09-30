from ..cli import command_serve, parse_args


def test_empty():
    command, kwargs = parse_args([])
    assert command is command_serve
    assert {"url", "port", "root"} <= set(kwargs)
