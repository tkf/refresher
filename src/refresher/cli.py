import argparse
import hashlib
import os
import sys
from functools import partial


def dhash(string):
    m = hashlib.sha1()
    m.update(string.encode())
    return int(m.hexdigest(), base=16)


def autoport(path):
    lower = 2000
    upper = 65535 + 1
    path = os.path.abspath(path)
    return dhash(path) % (upper - lower) + lower


async def command_serve_impl(url, open_browser, open_url_delay, **kwargs):
    import trio

    from .server import start_server

    async with trio.open_nursery() as nursery:
        nursery.start_soon(partial(start_server, **kwargs))
        if open_browser:
            await trio.sleep(open_url_delay)
            command_browse(url)


def command_serve(**kwargs):
    """
    Serve files in `root`.  This is the default behavior.
    """
    import trio

    trio.run(partial(command_serve_impl, **kwargs))


def command_browse(url, port=None, root=None):
    """
    Open browser without starting the server.
    """
    import webbrowser

    print("Opening:", url, file=sys.stderr)
    webbrowser.open(url)


def command_print_url(url, port=None, root=None):
    """
    Print URL from which files in `root` would be served.
    """
    print(url)


def preprocess_kwargs(*, port, **kwargs):
    root = kwargs["root"]
    if port.lower() == "auto":
        port_num = autoport(root)
    else:
        port_num = int(root)
    kwargs["port"] = port_num
    kwargs["url"] = f"http://localhost:{port_num}"

    return kwargs


def run_cli(*, command, **kwargs):
    import logging

    if kwargs.get("debug", False):
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level)

    command(**preprocess_kwargs(**kwargs))


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__
    )

    subparsers = parser.add_subparsers()

    def subp(argument, command):
        doc = command.__doc__
        try:
            title = next(filter(None, map(str.strip, (doc or "").splitlines())))
        except StopIteration:
            title = None
        p = subparsers.add_parser(
            argument,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help=title,
            description=doc,
        )
        p.set_defaults(command=command)
        return p

    def add_common_arguments(p):
        p.add_argument(
            "root",
            nargs="?",
            default=".",
            help="""
            Directory to serve.
            (default: %(default)s)
            """,
        )
        p.add_argument(
            "--port",
            default="auto",
            help="""
            Port number to use. "auto" (default) means to decide it based on
            `root`.
            """,
        )

    parser.set_defaults(command=command_serve)
    p = subp("serve", command_serve)
    add_common_arguments(p)
    p.add_argument(
        "--debug",
        action="store_true",
        help="""
        Enable debugging.
        """,
    )
    p.add_argument(
        "--open-url-delay",
        default=0.5,
        type=float,
        help="""
        Number of seconds to wait before the URL is open.
        """,
    )
    p.add_argument(
        "--open",
        dest="open_browser",
        action="store_const",
        const=True,
        default=True,
        help="""
        Open the page after starting the server (default).
        """,
    )
    p.add_argument(
        "--no-open",
        dest="open_browser",
        action="store_const",
        const=False,
        help="""
        Don't open the page after starting the server.
        """,
    )

    p = subp("browse", command_browse)
    add_common_arguments(p)

    p = subp("print-url", command_print_url)
    add_common_arguments(p)

    '''
    p = subp("pause", command_pause)
    add_common_arguments(p)
    p.add_argument(
        "--restart-after",
        type=float,
        metavar="SECONDS",
        help="""
        Restart after given number of seconds. -1 (defualt) means to
        never automatically restart.
        """,
    )

    p = subp("restart", command_restart)
    add_common_arguments(p)
    '''

    if args is None:
        args = sys.argv[1:]
    if not args:
        args = ["serve"]  # so that default above are used

    return parser.parse_args(args)


def main(args=None):
    run_cli(**vars(parse_args(args)))
