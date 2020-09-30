import trio

from .server import start_server


def main():
    trio.run(start_server)
