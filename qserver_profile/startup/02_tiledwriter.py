# qserver_profile/startup/02_tiledwriter.py
from __future__ import annotations

import os

from bluesky_tiled_plugins import TiledWriter
from tiled.client import from_uri

# for connecting to a remote Tiled server, set the following environment variables:
# export TILED_URI="http://<remote-tiled-ip>:8000"
# export TILED_API_KEY="<your-key>"

# RE is expected to exist (defined in 01_re.py)
RE  # noqa: F821

uri = os.environ.get("TILED_URI")
if not uri:
    print("[startup] TiledWriter disabled (set TILED_URI to enable)")
else:
    # from_uri reads TILED_API_KEY automatically if set (recommended).
    client = from_uri(uri)
    RE.subscribe(TiledWriter(client, batch_size=1))  # noqa: F821
    print(f"[startup] TiledWriter subscribed (TILED_URI={uri})")
