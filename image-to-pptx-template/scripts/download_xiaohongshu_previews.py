#!/usr/bin/env python3
"""Save observed Xiaohongshu preview image URLs without changing their bytes.

Pass a JSON array of ordered HTTPS URLs on standard input; never put signed URLs
or cookies into this script. The output is a compact record without URLs.
"""
import argparse
import hashlib
import json
import re
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image


def allowed_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return (parts.scheme == "https" and not parts.username and not parts.password
            and (host == "xhscdn.com" or host.endswith(".xhscdn.com")
                 or host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")))


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError("redirect destination is not an allowed image host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def save_images(urls, out_dir, opener=None):
    if not isinstance(urls, list) or not urls or any(not isinstance(url, str) for url in urls):
        raise ValueError("input must be a nonempty JSON array of image URLs")
    if any(not allowed_url(url) for url in urls):
        raise ValueError("only HTTPS Xiaohongshu image-host URLs are accepted")
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise ValueError("output directory must already exist")
    opener = opener or build_opener(SafeRedirect())
    records = []
    extensions = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
    for position, url in enumerate(urls, 1):
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaohongshu.com/"})
        with opener.open(request, timeout=30) as response:
            data = response.read()
        with Image.open(BytesIO(data)) as image:
            image_format, size = image.format, list(image.size)
            image.verify()
        if image_format not in extensions:
            raise ValueError(f"unsupported image format at position {position}")
        stem = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        if not stem or stem in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._!~-]+", stem):
            raise ValueError(f"unsafe image filename at position {position}")
        extension = extensions[image_format]
        filename = stem if stem.lower().endswith("." + extension) else stem + "." + extension
        output = out_dir / filename
        digest = hashlib.sha256(data).hexdigest()
        if output.exists():
            if hashlib.sha256(output.read_bytes()).hexdigest() != digest:
                raise FileExistsError(f"different file already exists: {filename}")
        else:
            with output.open("xb") as stream:
                stream.write(data)
        records.append({"position": position, "file": filename, "format": image_format,
                        "size_px": size, "bytes": len(data), "sha256": digest})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = save_images(json.load(sys.stdin), args.out_dir)
        print(json.dumps({"images": result}, ensure_ascii=False))
    except (ValueError, OSError, URLError, HTTPError) as exc:
        # Do not echo signed URLs, request headers or server responses.
        reason = getattr(exc, "reason", None)
        info = {"error": type(exc).__name__, "errno": getattr(exc, "errno", None),
                "reason_type": type(reason).__name__ if reason else None,
                "reason_errno": getattr(reason, "errno", None),
                "http_status": getattr(exc, "code", None)}
        print(json.dumps(info), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
