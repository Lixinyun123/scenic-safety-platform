#!/usr/bin/env python3
"""Inspect or update the station Hikvision stream without exposing credentials."""

from __future__ import annotations

import argparse
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


CAMERA_ENDPOINT = "http://192.168.1.50/ISAPI/Streaming/channels/{channel}"


def load_credentials(config_path: Path) -> tuple[str, str]:
    text = config_path.read_text(encoding="utf-8")
    match = re.search(r"^\s*source:\s*(rtsp://\S+/Streaming/Channels/101)\s*$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("station RTSP source not found")
    parsed = urllib.parse.urlsplit(match.group(1))
    if not parsed.username or parsed.password is None:
        raise RuntimeError("station RTSP credentials are missing")
    return urllib.parse.unquote(parsed.username), urllib.parse.unquote(parsed.password)


def build_opener(username: str, password: str, endpoint: str) -> urllib.request.OpenerDirector:
    manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    manager.add_password(None, endpoint, username, password)
    return urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(manager))


def request_xml(
    opener: urllib.request.OpenerDirector,
    method: str = "GET",
    body: bytes | None = None,
    endpoint: str = "",
) -> bytes:
    request = urllib.request.Request(
        endpoint,
        data=body,
        method=method,
        headers={"Content-Type": "application/xml", "Accept": "application/xml"},
    )
    with opener.open(request, timeout=8) as response:
        return response.read()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find(root: ET.Element, name: str) -> ET.Element | None:
    return next((element for element in root.iter() if local_name(element.tag) == name), None)


def value(root: ET.Element, name: str) -> str:
    element = find(root, name)
    return (element.text or "").strip() if element is not None else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/mediamtx.yml")
    parser.add_argument("--set-h264", action="store_true")
    parser.add_argument("--capabilities", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--channel", default="101", choices=("101", "102"))
    args = parser.parse_args()

    username, password = load_credentials(Path(args.config))
    endpoint = CAMERA_ENDPOINT.format(channel=args.channel)
    opener = build_opener(username, password, endpoint)
    if args.capabilities:
        capability_root = ET.fromstring(
            request_xml(opener, endpoint=endpoint + "/capabilities")
        )
        for element in capability_root.iter():
            if len(element) == 0 and (element.text or "").strip():
                attrs = ",".join(f"{key}={item}" for key, item in element.attrib.items())
                print(f"{local_name(element.tag)}={(element.text or '').strip()} [{attrs}]")
        return 0
    payload = request_xml(opener, endpoint=endpoint)
    root = ET.fromstring(payload)
    if args.dump:
        def dump(element: ET.Element, prefix: str = "") -> None:
            path = f"{prefix}/{local_name(element.tag)}"
            if len(element) == 0:
                print(f"{path}={(element.text or '').strip()}")
            for child in element:
                dump(child, path)

        dump(root)
        return 0

    before = value(root, "videoCodecType")
    if args.set_h264 and before.upper().replace(".", "") != "H264":
        # Older Hikvision firmware can return OK while ignoring XML whose
        # default namespace was rewritten to an ns0 prefix. Preserve the
        # exact payload and replace only codec-dependent text nodes.
        config_text = payload.decode("utf-8")
        config_text, codec_changes = re.subn(
            r"(<videoCodecType>)H\.265(</videoCodecType>)",
            r"\1H.264\2",
            config_text,
            count=1,
        )
        config_text = re.sub(
            r"<H265Profile>.*?</H265Profile>",
            "<H264Profile>Main</H264Profile>",
            config_text,
            count=1,
        )
        if codec_changes != 1:
            raise RuntimeError("H.265 codec node was not found")
        put_result = ET.fromstring(
            request_xml(opener, "PUT", config_text.encode("utf-8"), endpoint)
        )
        print("putStatus=" + value(put_result, "statusString"))
        print("putCode=" + value(put_result, "statusCode"))
        print("putSubStatus=" + value(put_result, "subStatusCode"))
        print("putErrorCode=" + value(put_result, "errorCode"))
        root = ET.fromstring(request_xml(opener, endpoint=endpoint))

    print("codec=" + value(root, "videoCodecType"))
    print("width=" + value(root, "videoResolutionWidth"))
    print("height=" + value(root, "videoResolutionHeight"))
    print("maxFrameRate=" + value(root, "maxFrameRate"))
    print("bitrate=" + value(root, "vbrUpperCap"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
