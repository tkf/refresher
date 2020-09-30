from ..cli import command_serve, parse_args, preprocess_kwargs


def parse_args_testing(args):
    ns = parse_args(args)
    kwargs = preprocess_kwargs(**vars(ns))
    return kwargs.pop("command"), kwargs


def test_empty():
    command, kwargs = parse_args_testing([])
    assert command is command_serve
    assert {"url", "port", "root"} <= set(kwargs)
