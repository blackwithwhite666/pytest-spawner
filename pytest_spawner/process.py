# coding: utf-8

import os
import shlex

import six
import pyuv

from .util import getcwd


class Stream(object):
    """Create stream to pass into subprocess."""

    def __init__(self, loop, emitter, process, label):
        self._loop = loop
        self._emitter = emitter
        self._process = process
        self._channel = pyuv.Pipe(self._loop)

        evtype_prefix = 'proc.%d.io.%s' % (self._process.pid, label)
        self.read_evtype = '%s.read' % evtype_prefix
        self.write_evtype = '%s.write' % evtype_prefix
        self.writelines_evtype = '%s.writelines' % evtype_prefix

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
        msg = dict(
            event=self.read_evtype, name=self._process.name, stream=self,
            pid=self._process.pid, data=data, error=error)
        self._emitter.publish(self.read_evtype, msg)

    def start(self):
        self._channel.start_read(self._on_read)
        self._emitter.subscribe(self.write_evtype, self._on_write)
        self._emitter.subscribe(self.writelines_evtype, self._on_writelines)

    def stop(self):
        if not self._channel.closed:
            self._channel.close()
        self._process = None


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

    def make_process(self, loop, emitter, pid, label, env=None, on_exit=None):
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
        return Process(loop, emitter, pid, label, self.cmd, **params)


class Process(object):
    """Class wrapping a process."""

    def __init__(self, loop, emitter, pid, name, cmd,
                 args=None, env=None, cwd=None, on_exit_cb=None):
        self._loop = loop
        self._emitter = emitter
        self._env = env or {}

        self.pid = pid
        self.name = name

        # set command
        self._cmd = six.b(cmd)
        if args is not None:
            if isinstance(args, six.string_types):
                self._args = shlex.split(six.b(args))
            else:
                self._args = [six.b(arg) for arg in args]

        else:
            splitted_args = shlex.split(self._cmd)
            if len(splitted_args) > 1:
                self._cmd = splitted_args[0]
            self._args = splitted_args

        self._cwd = cwd or getcwd()

        self._on_exit_cb = on_exit_cb
        self._process = None
        self._stdio = []
        self._streams = []
        self._stopped = False
        self._running = False

        self._graceful_time = 0
        self.graceful_timeout = None
        self.once = False

        self._exit_status = None
        self._term_signal = None

        self._setup_stdio()

    @property
    def running(self):
        return self._running

    def _setup_stdio(self):
        self._streams = [
            Stream(self._loop, self._emitter, self, 'stdin'),
            Stream(self._loop, self._emitter, self, 'stdout'),
            Stream(self._loop, self._emitter, self, 'stderr')
        ]
        self._stdio = [stream.stdio for stream in self._streams]

    def spawn(self, once=False, graceful_timeout=None, env=None):
        """Spawn the process."""

        self.once = once
        self.graceful_timeout = graceful_timeout

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
        for stream in self._streams:
            self._emitter.subscribe(stream.read_evtype, self._on_read_cb)
            stream.start()

    def _dispatch_cb(self):
        # handle the exit callback
        if self._on_exit_cb is not None and self._process is None and not self._streams:
            self._on_exit_cb(self, self._exit_status, self._term_signal)

    def _on_read_cb(self, evtype, msg):
        error = msg["error"]
        stream = msg["stream"]

        if error is not None and error & pyuv.errno.UV_EOF:
            stream.stop()
            self._streams.remove(stream)

            self._dispatch_cb()

    def _exit_cb(self, handle, exit_status, term_signal):
        self._running = False
        self._process = None
        handle.close()

        self._exit_status = exit_status
        self._term_signal = term_signal

        self._dispatch_cb()
