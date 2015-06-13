# conding: utf-8

import logging
import collections

import pyuv


class EventEmitter(object):

    def __init__(self, loop):
        self._events = {}
        self._wildcards = set()

        self._queue = collections.deque()
        self._wqueue = collections.deque()

        self._event_dispatcher = pyuv.Prepare(loop)
        self._event_dispatcher.start(self._send)
        self._event_dispatcher.ref = False
        self._spinner = pyuv.Idle(loop)

    def stop(self):
        """Close the event.
        This function clear the list of listeners and stop all idle callback.
        """
        self._wqueue.clear()
        self._queue.clear()
        self._events = {}
        self._wildcards = set()

        # close handlers
        if not self._event_dispatcher.closed:
            self._event_dispatcher.close()

        if not self._spinner.closed:
            self._spinner.close()

    def publish(self, evtype, *args, **kwargs):
        """Emit an event `evtype`.
        The event will be emitted asynchronously so we don't block here
        """
        if "." in evtype:
            parts = evtype.split(".")
            self._queue.append((parts[0], evtype, args, kwargs))
            key = []
            for part in parts:
                key.append(part)
                self._queue.append((".".join(key), evtype, args, kwargs))
        else:
            self._queue.append((evtype, evtype, args, kwargs))

        # emit the event for wildcards events
        self._wqueue.append((evtype, args, kwargs))

        # send the event for later
        self._dispatch_event()

    def subscribe(self, evtype, listener, once=False):
        """Subcribe to an event."""

        if evtype == ".": # wildcard
            self._wildcards.add((once, listener))
            return

        if evtype.endswith("."):
            evtype = evtype[:-1]

        if evtype not in self._events:
            self._events[evtype] = set()
        self._events[evtype].add((once, listener))

    def unsubscribe(self, evtype, listener, once=False):
        """Unsubscribe from an event."""

        if evtype == ".": # wildcard
            self._wildcards.remove((once, listener))
            return

        if evtype.endswith("."):
            evtype = evtype[:-1]

        self._events[evtype].remove((once, listener))
        if not self._events[evtype]:
            self._events.pop(evtype)

    def _dispatch_event(self):
        self._spinner.start(lambda h: None)

    def _send(self, handle):
        wqueue_len = len(self._wqueue)
        queue_len = len(self._queue)

        for _ in xrange(wqueue_len):
            evtype, args, kwargs = self._wqueue.popleft()
            if self._wildcards:
                self._wildcards = self._send_listeners(evtype, self._wildcards.copy(), *args, **kwargs)

        for _ in xrange(queue_len):
            pattern, evtype, args, kwargs = self._queue.popleft()
            # emit the event to all listeners
            if pattern in self._events:
                self._events[pattern] = self._send_listeners(evtype, self._events[pattern].copy(), *args, **kwargs)

        if not self._spinner.closed:
            self._spinner.stop()

    def _send_listeners(self, evtype, listeners, *args, **kwargs):
        to_remove = []
        for once, listener in listeners:
            try:
                listener(evtype, *args, **kwargs)
            except Exception:
                # we ignore all exception
                logging.error('Uncaught exception', exc_info=True)
                to_remove.append(listener)

            if once:
                # once event
                to_remove.append(listener)

        if to_remove:
            for listener in to_remove:
                try:
                    listeners.remove((True, listener))
                except KeyError:
                    pass
        return listeners

