# conding: utf-8

from __future__ import absolute_import, unicode_literals

import logging
import collections
import threading

import pyuv
import six


class EventEmitter(object):

    def __init__(self, loop):
        self._events = {}
        self._wildcards = set()
        self._lock = threading.RLock()

        self._queue = collections.deque()
        self._wqueue = collections.deque()

        self._event_dispatcher = pyuv.Prepare(loop)
        self._event_dispatcher.start(self._send)
        self._event_dispatcher.ref = False
        self._spinner = pyuv.Idle(loop)

        self._waker = pyuv.Async(loop, self._send)
        self._waker.ref = False

        self._stopped = False

    def stop(self):
        """Close the event.
        This function clear the list of listeners and stop all idle callback.
        """
        self._stopped = True
        self._wqueue.clear()
        self._queue.clear()
        self._events = {}
        self._wildcards = set()

        # close handlers
        if not self._event_dispatcher.closed:
            self._event_dispatcher.close()

        if not self._spinner.closed:
            self._spinner.close()

        if not self._waker.closed:
            self._waker.close()

    def _enqueue(self, evtype, args, kwargs):
        with self._lock:

            if len(evtype) > 1:
                key = []
                for part in evtype:
                    key.append(part)
                    self._queue.append((tuple(key), evtype, args, kwargs))
            else:
                self._queue.append((evtype, evtype, args, kwargs))

            # emit the event for wildcards events
            self._wqueue.append((evtype, args, kwargs))

    def publish(self, evtype, *args, **kwargs):
        """Emit an event `evtype`.
        The event will be emitted asynchronously so we don't block here
        """
        assert not self._spinner.closed, "spinner already closed"

        self._enqueue(evtype, args, kwargs)

        # send the event for later
        self._spinner.start(lambda h: None)

    def publish_from_thread(self, evtype, *args, **kwargs):
        """Thread-safe version of publish."""
        assert not self._waker.closed, "waker already closed"

        self._enqueue(evtype, args, kwargs)

        # wake up loop for processing
        self._waker.send()

    def subscribe(self, evtype, listener, once=False):
        """Subcribe to an event."""
        assert not self._stopped, "emitter is already stopped"

        with self._lock:

            if not evtype: # wildcard
                self._wildcards.add((once, listener))
                return

            if evtype not in self._events:
                self._events[evtype] = set()
            self._events[evtype].add((once, listener))

    def unsubscribe(self, evtype, listener, once=False):
        """Unsubscribe from an event."""
        assert not self._stopped, "emitter is already stopped"

        with self._lock:

            if not evtype: # wildcard
                self._wildcards.remove((once, listener))
                return

            self._events[evtype].remove((once, listener))
            if not self._events[evtype]:
                self._events.pop(evtype)

    def _send(self, handle):
        wqueue_len = len(self._wqueue)
        queue_len = len(self._queue)

        for _ in six.moves.range(wqueue_len):
            evtype, args, kwargs = self._wqueue.popleft()
            if self._wildcards:
                with self._lock:
                    self._send_listeners(evtype, self._wildcards, *args, **kwargs)

        for _ in six.moves.range(queue_len):
            pattern, evtype, args, kwargs = self._queue.popleft()
            # emit the event to all listeners
            if pattern in self._events:
                with self._lock:
                    self._send_listeners(evtype, self._events[pattern], *args, **kwargs)

        if not self._spinner.closed:
            self._spinner.stop()

    def _send_listeners(self, evtype, listeners, *args, **kwargs):
        to_remove = []
        for once, listener in list(listeners):
            try:
                listener(evtype, *args, **kwargs)
            except Exception:
                # we ignore all exception
                logging.error('Uncaught exception in %r', listener, exc_info=True)

            if once:
                # once event
                to_remove.append(listener)

        if to_remove:
            for listener in to_remove:
                try:
                    listeners.remove((True, listener))
                except KeyError:
                    pass
