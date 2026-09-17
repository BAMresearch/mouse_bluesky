#! /bin/bash

# earlier version used configs on vsi-db but stops with network trouble
# mouse-bluesky enqueue /mnt/vsi-db/Measurements/SAXS002/logbooks/Logbook_MOUSE.xlsx /mnt/vsi-db/Proposals/SAXS002/ --root-path /home/ws8665-epics/data --config-root /mnt/vsi-db/Measurements/SAXS002/data/configurations/ --zmq tcp://127.0.0.1:60615
mouse-bluesky enqueue /mnt/vsi-db/Measurements/SAXS002/logbooks/Logbook_MOUSE.xlsx /mnt/vsi-db/Proposals/SAXS002/ --root-path /home/ws8665-epics/data --config-root /home/ws8665-epics/data/configurations/ --zmq tcp://127.0.0.1:60615
