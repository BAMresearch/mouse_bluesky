# qserver_profile/startup/02_tiledwriter.py
from __future__ import annotations

import os

from bluesky.callbacks.tiled_writer import TiledWriter
from tiled.client import from_uri

# for connecting to a remote Tiled server, set the following environment variables:
# export TILED_URI="http://<remote-tiled-ip>:8000"
# export TILED_API_KEY="<your-key>"

# RE is expected to exist (defined in 01_re.py)
# RE  # noqa: F821

uri = "https://tiled.scicat65.ddnss.de"  # os.environ.get("TILED_URI") does not work
# key = os.environ.get("TILED_API_KEY")
with open("/home/ws8665-epics/.tiled_api.key", "r") as f:
    key = f.read().strip()

if not uri:
    print("[startup] TiledWriter disabled (set TILED_URI to enable)")
else:
    # from_uri reads TILED_API_KEY automatically if set (recommended).
    tiled_client = from_uri(uri, api_key=key)
    RE.subscribe(TiledWriter(tiled_client, batch_size=1))  # noqa: F821
    print(f"[startup] TiledWriter subscribed (TILED_URI={uri})")
