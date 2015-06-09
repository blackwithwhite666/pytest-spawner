# coding: utf-8

import os
import shlex

import six
import pyuv

from .events import EventEmitter
from .util import getcwd


class Stream(object):
    """Create stream to pass into subprocess."""

    def __init__(self, loop, process, label):
        self._loop = loop
        self._process = process
        self._channel = pyuv.Pipe(self._loop)
        self._label = label
        self._emitter = EventEmitter()

    @property
    def stdio(self):
        return pyuv.StdIO(
            stream=self._channel,
            flags=pyuv.UV_CREATE_PIPE | pyuv.UV_READABLE_PIPE | pyuv.UV_WRITABLE_PIPE)

    def _on_write(self, evtype, data):
        self._channel.write(data)

    def _on_writelines(self, evtype, data):
        self._channel.writelines(data)

    def _on_read(self, handle, data, error):
        if not data:
            return

        msg = dict(
            event=self._label, name=self._process.name,
            pid=self._process.pid, data=data, error=error)
        self._emitter.publish(self._label, msg)

    def subscribe(self, label, listener):
        self._emitter.subscribe(label, listener)

    def unsubscribe(self, label, listener):
        self._emitter.unsubscribe(label, listener)

    def write(self, data):
        self._emitter.publish("WRITE", data)

    def writelines(self, data):
        self._emitter.publish("WRITELINES", data)

    def start_reading(self):
        self._channel.start_read(self._on_read)

    def start_writing(self):
        self._emitter.subscribe("WRITE", self._on_write)
        self._emitter.subscribe("WRITELINES", self._on_writelines)

    def stop(self):
        if self._channel.active:
            self._channel.close()


class ProcessConfig(object):
    """Object to maintain a process config."""

    DEFAULT_PARAMS = {
        "args": None,
        "env": None,
        "cwd": None,
    }

    def __init__(self, name, cmd, **settings):
        self.name = name
        self.cmd = cmd
        self.settings = settings

    def make_process(self, loop, pid, label, env=None, on_exit=None):
        params = {}
        for name, default in self.DEFAULT_PARAMS.items():
            params[name] = self.settings.get(name, default)

        os_env = self.settings.get('os_env', False)
        if os_env:
            env = params.get('env') or {}
            env.update(os.environ)
            params['env'] = env

        if env is not None:
            params['env'].update(env)

        params['on_exit_cb'] = on_exit
        return Process(loop, pid, label, self.cmd, **params)


class Process(object):
    """Class wrapping a process."""

    def __init__(self, loop, pid, name, cmd, args=None, env=None, cwd=None, on_exit_cb=None):
        self._loop = loop
        self.pid = pid
        self.name = name
        self._env = env or {}

        # set command
        self._cmd = six.b(cmd)
        if args is not None:
            if isinstance(args, six.string_types):
                self._args = shlex.split(six.b(args))
            else:
                self._args = [six.b(arg) for arg in args]

        else:
            splitted_args = shlex.split(self._cmd)
            if len(splitted_args) == 1:
                self._args = []
            else:
                self._cmd = splitted_args[0]
                self._args = splitted_args[1:]

        self._cwd = cwd or getcwd()

        self._redirect_stdin = None
        self._redirect_stdout = None
        self._redirect_stderr = None

        self._on_exit_cb = on_exit_cb
        self._process = None
        self._stdio = []
        self._stopped = False
        self._graceful_time = 0
        self._graceful_timeout = None
        self._once = False
        self._running = False

        self._setup_stdio()

    def _setup_stdio(self):
        self._redirect_stdin = Stream(self._loop, self, 'stdin')
        self._redirect_stdout = Stream(self._loop, self, 'stdout')
        self._redirect_stderr = Stream(self._loop, self, 'stderr')
        self._stdio = [
            self._redirect_stdin.stdio,
            self._redirect_stdout.stdio,
            self._redirect_stderr.stdio
        ]

    def spawn(self, once=False, graceful_timeout=None, env=None):
        """Spawn the process."""

        self._once = once
        self._graceful_timeout = graceful_timeout

        if env is not None:
            self._env.update(env)

        kwargs = dict(
            executable=self._cmd,
            exit_callback=self._exit_cb,
            args=self._args,
            env=self._env,
            cwd=self._cwd,
            stdio=self._stdio)

        # spawn the process
        self._process = pyuv.Process(self._loop)
        self._process.spawn(self._loop, **kwargs)
        self._running = True

        # start redirecting IO
        self._redirect_stderr.start_reading()
        self._redirect_stdout.start_reading()
        self._redirect_stdin.start_writing()

    def _exit_cb(self, handle, exit_status, term_signal):
        self._redirect_stdin.stop()
        self._redirect_stdout.stop()
        self._redirect_stderr.stop()

        self._running = False
        handle.close()

        # handle the exit callback
        if self._on_exit_cb is not None:
            self._on_exit_cb(self, exit_status, term_signal)
