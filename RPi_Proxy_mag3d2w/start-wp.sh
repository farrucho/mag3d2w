#!/bin/bash

sh ./video-stream.sh > /dev/null 2>&1 &

killall .venv/bin/python3
.venv/bin/python3 main.py > /dev/null 2>&1 &
