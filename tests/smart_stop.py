#!/usr/bin/env python

import signal
import time
import sys

stop_flag = False
wait_before_stop = 1


def exit_gracefully(signum, frame):
    global stop_flag
    print("SIGTERM catched, let's wait %i s" % wait_before_stop)
    time.sleep(wait_before_stop)
    print("stop_flag setted")
    stop_flag = True


if len(sys.argv) > 1:
    wait_before_stop = int(sys.argv[1])
signal.signal(signal.SIGTERM, exit_gracefully)
while True:
    time.sleep(0.1)
    if stop_flag:
        break
print("clean exit")
sys.exit(3)
