# coding: utf-8

from __future__ import absolute_import, unicode_literals

import heapq
import operator
import signal
import collections

import pyuv

from .util import nanotime


class ProcessTracker(object):

    def __init__(self, loop):
        self._processes = []
        self._done_cb = None
        self._check_timer = pyuv.Timer(loop)

    def start(self, interval=0.1):
        self._check_timer.start(self._on_check, interval, interval)

    def on_done(self, callback):
        self._done_cb = callback

    def stop(self):
        self._check_timer.stop()
        self._processes = []

    def close(self):
        self._processes = []
        self._done_cb = None
        if not self._check_timer.closed:
            self._check_timer.close()

    def check(self, process, graceful_timeout=10000000000):
        process.graceful_time = graceful_timeout + nanotime()
        heapq.heappush(self._processes, process)

    def uncheck(self, process):
        if process in self._processes:
            del self._processes[operator.indexOf(self._processes, process)]

    def _on_check(self, handle):
        # this function check if a process that need to be stopped after
        # a given graceful time is still in the stopped process. If yes
        # the process is killed. It let the possibility to let the time
        # to some worker to quit.
        #
        # The garbage collector run every 0.1s .
        while True:
            if not len(self._processes):
                # done callback has been set, run it
                if self._done_cb is not None:
                    self._done_cb()
                    self._done_cb = None

                # nothing in the queue, quit
                break

            # check the diff between the time it is now and the
            # graceful time set when the worker was stopped
            process = heapq.heappop(self._processes)
            now = nanotime()
            delta = process.graceful_time - now
            if delta > 0:
                # we have anything to do, put the process back in
                # the heap and return
                if process.active:
                    heapq.heappush(self._processes, process)
                break
            else:
                # a process need to be kill. Send a SIGKILL signal
                process.kill(signal.SIGKILL)

                # and close it. (maybe we should just close it)
                process.close()


class ProcessState(object):
    """Object used by the manager to maintain the process state for a config."""

    def __init__(self, config):
        self.config = config
        self.name = self.config.name
        self.stopped = False

        self._running = collections.deque()

    @property
    def active(self):
        return len(self._running) > 0

    def make_process(self, loop, emitter, pid, on_exit):
        """Create an OS process using this template."""
        return self.config.make_process(loop, emitter, pid, self.name, on_exit=on_exit)

    def queue(self, process):
        """Put one OS process in the running queue."""
        self._running.append(process)

    def dequeue(self):
        """Retrieved one OS process from the queue (FIFO)."""
        return self._running.popleft()

    def remove(self, process):
        """Remove an OS process from the running processes."""
        try:
            self._running.remove(process)
        except ValueError:
            pass

    @property
    def os_pids(self):
        """Return pid of running processes."""
        return [process.os_pid for process in self._running]
