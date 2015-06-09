# coding: utf-8

import os
import time


def getcwd():
    """Returns current path, try to use PWD env first"""
    try:
        a = os.stat(os.environ['PWD'])
        b = os.stat(os.getcwd())
        if a.ino == b.ino and a.dev == b.dev:
            working_dir = os.environ['PWD']
        else:
            working_dir = os.getcwd()
    except Exception:
        working_dir = os.getcwd()
    return working_dir


def nanotime(s=None):
    """Convert seconds to nanoseconds. If s is None, current time is returned."""
    if s is not None:
        return int(s) * 1000000000
    return time.time() * 1000000000
