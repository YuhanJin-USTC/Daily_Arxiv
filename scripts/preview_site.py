"""Serve a local site and a read-only migration snapshot on loopback."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, site, data, index, before=None, **kwargs):
        self.site = site
        self.data = data
        self.index = index
        self.before = before
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        path = unquote(urlsplit(path).path)
        if path == "/daily-arxiv/assets/researcher-index.json":
            return str(self.index)
        if path.startswith("/daily-arxiv/data/"):
            root, relative = self.data / "data", path.removeprefix("/daily-arxiv/data/")
        elif path == "/daily-arxiv/assets/file-list.txt":
            root, relative = self.data / "assets", "file-list.txt"
        elif path.startswith("/daily-arxiv/"):
            root, relative = self.site, path.removeprefix("/daily-arxiv/")
        elif path.startswith("/before/") and self.before:
            root, relative = self.before, path.removeprefix("/before/")
        else:
            return str(self.site / "__not_found__")
        target = (root / relative).resolve()
        if not target.is_relative_to(root.resolve()):
            return str(self.site / "__not_found__")
        return str(target)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    handler = partial(
        PreviewHandler,
        site=args.site,
        data=args.data,
        index=args.index,
        before=args.before,
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Local preview: http://127.0.0.1:{args.port}/daily-arxiv/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
