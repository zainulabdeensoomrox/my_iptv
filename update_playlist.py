import os
import re
import requests

PORTAL_URL = "http://line.tivi-one.net:80/server/load.php"
MAC_ADDRESS = "A0:BB:3E:75:52:64"

# Your 7 New Zealand Sky Sport channels
CHANNELS = {
    "Sky Sport 1 NZ": "809392",
    "Sky Sport 2 NZ": "809378",
    "Sky Sport 3 NZ": "809377",
    "Sky Sport 4 NZ": "809376",
    "Sky Sport 5 NZ": "809375",
    "Sky Sport 6 NZ": "809374",
    "Sky Sport 7 NZ": "809373"
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3",
    "Cookie": f"mac={MAC_ADDRESS}; stb_lang=en; timezone=Asia/Karachi;",
    "X-User-Agent": "Model: MAG250; Link: WiFi"
})

def get_stalker_token():
    url = f"{PORTAL_URL}?type=stb&action=handshake&JsHttpRequest=1-xml"
    res = session.get(url, timeout=10)
    data = res.json()
    token = data.get("js", {}).get("token")
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})
    return token

def fetch_stream_url(channel_id):
    cmd = f"ffrt http://localhost/ch/{channel_id}"
    url = f"{PORTAL_URL}?type=itv&action=create_link&cmd={cmd}&JsHttpRequest=1-xml"
    try:
        res = session.get(url, timeout=10)
        data = res.json()
        raw_cmd = data.get("js", {}).get("cmd", "")
        match = re.search(r'https?://[^\s"]+', raw_cmd)
        return match.group(0) if match else None
    except Exception as e:
        print(f"Error fetching channel {channel_id}: {e}")
        return None

def generate_m3u():
    token = get_stalker_token()
    if not token:
        print("Failed to authenticate with Stalker Portal.")
        return

    m3u_lines = ["#EXTM3U\n"]
    for name, ch_id in CHANNELS.items():
        stream_url = fetch_stream_url(ch_id)
        if stream_url:
            m3u_lines.append(f"#EXTINF:-1 tvg-id=\"{ch_id}\",{name}")
            m3u_lines.append(f"{stream_url}\n")
            print(f"[SUCCESS] {name} updated")
        else:
            print(f"[FAILED] {name}")

    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.writelines("\n".join(m3u_lines))

if __name__ == "__main__":
    generate_m3u()
