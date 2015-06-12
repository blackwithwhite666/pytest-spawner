# conding: utf-8

import logging


class EventEmitter(object):

    def __init__(self):
        self._events = {}
        self._wildcards = set()

    def publish(self, evtype, *args, **kwargs):
        """Emit an event `evtype`.
        The event will be emitted asynchronously so we don't block here
        """
        queue = []
        wqueue = []

        if "." in evtype:
            parts = evtype.split(".")
            queue.append((parts[0], evtype, args, kwargs))
            key = []
            for part in parts:
                key.append(part)
                queue.append((".".join(key), evtype, args, kwargs))
        else:
            queue.append((evtype, evtype, args, kwargs))

        # emit the event for wildcards events
        wqueue.append((evtype, args, kwargs))

        # send the event for later
        self._send(queue, wqueue)

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

    def _send(self, queue, wqueue):
        for evtype, args, kwargs in wqueue:
            if self._wildcards:
                self._wildcards = self._send_listeners(evtype, self._wildcards.copy(), *args, **kwargs)

        for pattern, evtype, args, kwargs in queue:
            # emit the event to all listeners
            if pattern in self._events:
                self._events[pattern] = self._send_listeners(evtype, self._events[pattern].copy(), *args, **kwargs)

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

