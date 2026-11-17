#! /bin/bash

# run this in the "bluesky_RE" screen:
start-re-manager --ipython-dir /home/ws8665-epics/code/mouse_bluesky/qserver_profile --startup-profile mouse --use-ipython-kernel ON --ipython-matplotlib qt6 --zmq-control-addr tcp://127.0.0.1:60615 --zmq-info-addr tcp://127.0.0.1:60625
