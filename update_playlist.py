#!/usr/bin/env python3
"""Generate an M3U playlist from a Stalker/Ministra portal."""

import argparse
import logging
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_PORTAL = "http://line.tivi-one.net:80/server/load.php"
DEFAULT_MAC = "A0:BB:3E:75:52:64"
DEFAULT_UA = (
    "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
    "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3"
)

CHANNELS = {
    "Sky Sport 1 NZ": "809392",
    "Sky Sport 2 NZ": "809378",
    "Sky Sport 3 NZ": "809377",
    "Sky Sport 4 NZ": "809376",
    "Sky Sport 5 NZ": "809375",
    "Sky Sport 6 NZ": "809374",
    "Sky Sport 7 NZ": "809373",
}

log = logging.getLogger("stalker-m3u")


class StalkerClient:
    def __init__(self, portal: str, mac: str, user_agent: str, timeout: int = 10):
        self.portal = portal
        self.timeout = timeout
        self.session = requests.Session()

        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
        self.session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))

        self.session.headers.update({
            "User-Agent": user_agent,
            "X-User-Agent": "Model: MAG250; Link: WiFi",
        })
        self.session.cookies.update({
            "mac": mac,
            "stb_lang": "en",
            "timezone": "Asia/Karachi",
        })

    def _call(self, **params) -> dict:
        params["JsHttpRequest"] = "1-xml"
        res = self.session.get(self.portal, params=params, timeout=self.timeout)
        res.raise_for_status()
        return res.json().get("js", {})

    def authenticate(self) -> bool:
        js = self._call(type="stb", action="handshake")
        token = js.get("token") if isinstance(js, dict) else None
        if not token:
            return False
        self.session.headers["Authorization"] = f"Bearer {token}"
        try:
            self._call(type="stb", action="get_profile")
        except requests.RequestException as exc:
            log.debug("get_profile failed (continuing anyway): %s", exc)
        return True

    def get_stream_url(self, channel_id: str) -> str | None:
        cmd = f"ffrt http://localhost/ch/{channel_id}"
        try:
            js = self._call(type="itv", action="create_link", cmd=cmd)
        except (requests.RequestException, ValueError) as exc:
            log.error("Channel %s: request failed: %s", channel_id, exc)
            return None

        raw = js.get("cmd", "") if isinstance(js, dict) else ""
        for part in raw.split():
            if part.startswith(("http://", "https://")):
                return part.strip("\"'")
        return None


def build_entry(name: str, ch_id: str, url: str, ua: str, style: str) -> list[str]:
    lines = [f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}",{name}']
    if style in ("vlcopt", "all"):
        lines.append(f"#EXTVLCOPT:http-user-agent={ua}")
    lines.append(f"{url}|User-Agent={ua}" if style in ("pipe", "all") else url)
    return lines


def write_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--portal", default=os.getenv("PORTAL_URL", DEFAULT_PORTAL))
    ap.add_argument("--mac", default=os.getenv("STB_MAC", DEFAULT_MAC))
    ap.add_argument("--user-agent", default=DEFAULT_UA)
    ap.add_argument("--output", default="playlist.m3u")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--header-style", choices=("pipe", "vlcopt", "all"), default="all",
        help="how to pass the User-Agent to the player (default: all)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.mac:
        log.error("No MAC address given. Use --mac or set STB_MAC.")
        return 1

    client = StalkerClient(args.portal, args.mac, args.user_agent)
    try:
        if not client.authenticate():
            log.error("Authentication failed (no token returned).")
            return 1
    except (requests.RequestException, ValueError) as exc:
        log.error("Could not reach portal: %s", exc)
        return 1

    results: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(client.get_stream_url, cid): name
                   for name, cid in CHANNELS.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            results[name] = fut.result()
            log.info("%s %s", "OK    " if results[name] else "FAILED", name)

    lines = ["#EXTM3U"]
    for name, cid in CHANNELS.items():
        if url := results.get(name):
            lines += build_entry(name, cid, url, args.user_agent, args.header_style)

    ok = sum(1 for u in results.values() if u)
    if ok == 0:
        log.error("No streams resolved; playlist not written.")
        return 1

    write_atomic(args.output, "\n".join(lines) + "\n")
    log.info("Wrote %d/%d channels to %s", ok, len(CHANNELS), args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
