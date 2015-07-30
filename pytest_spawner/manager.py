# conding: utf-8

from __future__ import absolute_import, unicode_literals

import threading
import collections
import signal

import pyuv

from .state import ProcessTracker, ProcessState
from .events import EventEmitter
from .error import StateNotFound, StateConflict

DEFAULT_GRACEFUL_TIMEOUT = 10.0


class Manager(object):

    load_evtype = ('load', )
    unload_evtype = ('unload', )
    commit_evtype = ('commit', )
    start_evtype = ('start', )
    stop_evtype = ('stop', )
    spawn_evtype = ('spawn', )
    reap_evtype = ('reap', )
    exit_evtype = ('exit', )

    def __init__(self):
        self._loop = pyuv.Loop()

        self._thread = threading.Thread(target=self._target)
        self._thread.daemon = True
        self._events = EventEmitter(self._loop)

        # initialize the process tracker
        self._tracker = ProcessTracker(self._loop)

        # maintain process configurations
        self._states = collections.OrderedDict()
        self._running = {}

        self._started = False
        self._waker = None
        self._lock = threading.RLock()

        self._max_process_id = 0

    def _publish(self, evtype, **ev):
        event = {'event': evtype}
        event.update(ev)
        self._events.publish(evtype, event)

    def _publish_from_thread(self, evtype, **ev):
        # NB: don't call this function from critical section, it will lead to deadlock
        event = {'event': evtype}
        event.update(ev)
        self._events.publish_from_thread(evtype, event)

    def start(self):
        if self._started:
            raise RuntimeError('Manager has been started already')

        self._thread.start()

    def stop(self):
        if not self._started:
            return

        self._waker.send()
        self._thread.join()

    def subscribe(self, evtype, listener, once=False):
        """Subcribe to an event."""
        self._events.subscribe(evtype, listener, once)

    def unsubscribe(self, evtype, listener, once=False):
        """Unsubscribe from an event."""
        self._events.unsubscribe(evtype, listener, once)

    def load(self, config, start=True):
        """Run process with given config of type `.process.ProcessConfig`."""
        with self._lock:
            if config.name in self._states:
                raise StateConflict()

            state = ProcessState(config)
            self._states[config.name] = state

        # notify about new config
        self._publish_from_thread(
            self.load_evtype, name=config.name, state=state, start=start)

    def _on_load(self, evtype, data):
        if data['start']:
            self._start_process(data['state'])

    def unload(self, name):
        """Unload a process config."""
        with self._lock:
            if name not in self._states:
                raise StateNotFound()

            # get the state and remove it from the context
            state = self._states.pop(name)

        # notify that we unload the process
        self._publish_from_thread(
            self.unload_evtype, name=name, state=state)

    def exists(self, name):
        with self._lock:
            return name in self._states

    def get_os_pids(self, name):
        with self._lock:
            if name not in self._states:
                raise StateNotFound()

            return self._states[name].os_pids

    def _on_unload(self, evtype, data):
        # stop the process now.
        self._stop_process(data['state'])

    def commit(self, name, graceful_timeout=None, env=None):
        """The process won't be kept alived at the end."""
        with self._lock:
            state = self._get_state(name)

        # notify that we are starting the process
        self._publish_from_thread(
            self.commit_evtype, name=state.name, state=state,
            graceful_timeout=graceful_timeout, env=env)

    def _on_commit(self, evtype, data):
        self._spawn_process(
            state=data['state'], graceful_timeout=data['graceful_timeout'],
            env=data['env'], once=True)

    def _get_process_id(self):
        """Generate a process id."""
        with self._lock:
            self._max_process_id += 1
            return self._max_process_id

    def _get_state(self, name):
        if name not in self._states:
            raise StateNotFound()
        return self._states[name]

    def _start_process(self, state):
        with self._lock:
            # notify that we are starting the process
            self._publish(self.start_evtype, name=state.name)

            self._spawn_process(state)

    def _stop_process(self, state):
        with self._lock:
            # notify that we are stoppping the process
            self._publish(self.stop_evtype, name=state.name)

            self._reap_processes(state)

    def _spawn_process(self, state, once=False, graceful_timeout=None, env=None):
        """Spawn a new process and add it to the state."""
        # get internal process id
        pid = self._get_process_id()

        # start process
        process = state.make_process(self._loop, self._events, pid, self._on_process_exit)
        process.spawn(once, graceful_timeout or DEFAULT_GRACEFUL_TIMEOUT, env)

        # add the process to the running state
        state.queue(process)

        # we keep a list of all running process by id here
        self._running[pid] = process

        # notify subscribers about new process
        ev_details = dict(name=process.name, pid=pid, os_pid=process.os_pid)
        self._publish(self.spawn_evtype, **ev_details)
        self._publish(process.config.spawn_evtype, **ev_details)

    def _reap_processes(self, state):
        while True:
            # remove the process from the running processes
            try:
                process = state.dequeue()
            except IndexError:
                return

            # remove the pid from the running processes
            if process.pid in self._running:
                self._running.pop(process.pid)

            # stop the process
            process.kill(signal.SIGTERM)

            # track this process to make sure it's killed after the graceful time
            self._tracker.check(process, process.graceful_timeout)

            # notify others that the process is beeing reaped
            ev_details = dict(name=process.name, pid=process.pid, os_pid=process.os_pid)
            self._publish(self.reap_evtype, **ev_details)
            self._publish(process.config.reap_evtype, **ev_details)

    def _target(self):

        def wakeup(handle):
            handle.close()
            self._stop()

        self._waker = pyuv.Async(self._loop, wakeup)

        # start the process tracker
        self._tracker.start()

        # manage processes
        self._events.subscribe(self.load_evtype, self._on_load)
        self._events.subscribe(self.commit_evtype, self._on_commit)
        self._events.subscribe(self.exit_evtype, self._on_exit)
        self._events.subscribe(self.unload_evtype, self._on_unload)

        self._started = True
        self._loop.run()

    def _stop(self):
        # stop should be synchronous. We need to first stop the
        # processes and let the applications know about it. It is
        # actually done by setting on startup a timer waiting that all
        # processes have stopped to run.

        def shutdown():
            self._started = False
            self._tracker.stop()
            self._events.stop()

        # stop all processes
        with self._lock:
            for state in self._states.values():
                if not state.stopped:
                    state.stopped = True
                    self._reap_processes(state)

            self._tracker.on_done(shutdown)

    def _on_exit(self, evtype, msg):
        name = msg['name']
        once = msg.get('once', False)

        with self._lock:
            try:
                state = self._get_state(name)
            except StateNotFound:
                # race condition, we already removed this process
                return

            # eventually restart the process
            if not state.stopped and not once:
                # manage the template, eventually restart a new one.
                if state.stopped:
                    return

                if not state.active:
                    self._spawn_process(state)

    def _on_process_exit(self, process, **kwargs):
        with self._lock:
            # maybe uncheck this process from the tracker
            self._tracker.uncheck(process)

            # unexpected exit, remove the process from the list of running processes
            if process.pid in self._running:
                self._running.pop(process.pid)

            try:
                state = self._get_state(process.name)
            except StateNotFound:
                pass
            else:
                state.remove(process)

            # notify other that the process exited
            ev_details = dict(
                name=process.name,
                pid=process.pid,
                once=process.once,
                **kwargs)

            self._publish(self.exit_evtype, **ev_details)
            self._publish(process.config.exit_evtype, **ev_details)
