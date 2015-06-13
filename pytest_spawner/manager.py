# conding: utf-8

import threading
import collections
import signal

import pyuv

from .state import ProcessTracker, ProcessState
from .events import EventEmitter
from .error import ProcessNotFound, ProcessConflict

DEFAULT_GRACEFUL_TIMEOUT = 10.0


class Manager(object):

    def __init__(self):
        self._loop = pyuv.Loop.default_loop()

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

    def start(self):
        if self._started:
            raise RuntimeError('Manager has been started already')

        self._thread.start()

    def stop(self):
        if not self._started:
            return

        self._waker.send()
        self._thread.join()

    def load(self, config, start=True):
        """Run process with given config of type `.process.ProcessConfig`."""
        with self._lock:
            if config.name in self._states:
                raise ProcessConflict()

            state = ProcessState(config)
            self._states[config.name] = state
            self._publish('load', name=config.name)

        if start:
            self._start_process(state)

    def unload(self, name):
        """Unload a process config."""

        with self._lock:
            if name not in self._states:
                raise ProcessNotFound()

            # get the state and remove it from the context
            state = self._states.pop(name)

            # notify that we unload the process
            self._publish('unload', name=name)

        # stop the process now.
        self._stop_process(state)

    def commit(self, name, graceful_timeout=None, env=None):
        """The process won't be kept alived at the end."""

        with self._lock:
            state = self._get_state(name)

            # notify that we are starting the process
            self._publish('commit', name=state.name)

            self._spawn_process(
                state=state,
                once=True,
                graceful_timeout=graceful_timeout,
                env=env)

    def _get_process_id(self):
        """Generate a process id."""
        with self._lock:
            self._max_process_id += 1
            return self._max_process_id

    def _get_state(self, name):
        if name not in self._states:
            raise ProcessNotFound()
        return self._states[name]

    def _start_process(self, state):
        with self._lock:
            # notify that we are starting the process
            self._publish('start', name=state.name)

            self._spawn_process(state)

    def _stop_process(self, state):
        with self._lock:
            # notify that we are stoppping the process
            self._publish('stop', name=state.name)

            self._reap_processes(state)

    def _manage_processes(self, state):
        if state.stopped:
            return

        if not state.active:
            self._spawn_process(state)

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

        self._publish('spawn', name=process.name, pid=pid, os_pid=process.os_pid)
        self._publish('state.%s.spawn' % process.name, name=process.name, pid=pid, os_pid=process.os_pid)
        self._publish('proc.%s.spawn' % pid, name=process.name, pid=pid, os_pid=process.os_pid)

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
            self._publish('reap', name=process.name, pid=process.pid, os_pid=process.os_pid)
            self._publish('state.%s.reap' % process.name, name=process.name, pid=process.pid, os_pid=process.os_pid)
            self._publish('proc.%s.reap' % process.pid, name=process.name, pid=process.pid, os_pid=process.os_pid)

    def _publish(self, evtype, **ev):
        event = {'event': evtype}
        event.update(ev)
        self._events.publish(evtype, event)

    def _target(self):

        def wakeup(handle):
            handle.close()
            self._stop()

        self._waker = pyuv.Async(self._loop, wakeup)

        # start the process tracker
        self._tracker.start()

        # manage processes
        self._events.subscribe('exit', self._on_exit)

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
            except ProcessNotFound:
                # race condition, we already removed this process
                return

            # eventually restart the process
            if not state.stopped and not once:
                # manage the template, eventually restart a new one.
                self._manage_processes(state)

    def _on_process_exit(self, process, exit_status, term_signal):
        with self._lock:
            # maybe uncheck this process from the tracker
            self._tracker.uncheck(process)

            # unexpected exit, remove the process from the list of running processes
            if process.pid in self._running:
                self._running.pop(process.pid)

            try:
                state = self._get_state(process.name)
            except ProcessNotFound:
                pass
            else:
                state.remove(process)

            # notify other that the process exited
            ev_details = dict(
                name=process.name,
                pid=process.pid,
                exit_status=exit_status,
                term_signal=term_signal,
                once=process.once)

            self._publish('exit', **ev_details)
            self._publish('state.%s.exit' % process.name, **ev_details)
