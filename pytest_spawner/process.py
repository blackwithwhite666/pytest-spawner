# coding: utf-8

import os
import errno
import shlex

import six
import pyuv

from .util import getcwd, set_nonblocking

pyuv.Process.disable_stdio_inheritance()


class Stream(object):
    """Create stream to pass into subprocess."""

    def __init__(self, loop, emitter, process, label):
        self._loop = loop
        self._emitter = emitter
        self._process = process
        self._channel = pyuv.Pipe(self._loop)

        self._evtype_prefix = ('proc', self._process.pid)
        self.read_evtype = self._evtype_prefix + ('read', label)
        self.write_evtype = self._evtype_prefix + ('write', label)
        self.writelines_evtype = self._evtype_prefix + ('writelines', label)

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
            event=self.read_evtype, name=self._process.name, stream=self,
            pid=self._process.pid, data=data)
        self._emitter.publish(self.read_evtype, msg)

    def speculative_read(self):
        fd = self._channel.fileno()
        set_nonblocking(fd)
        while True:
            try:
                buf = os.read(fd, 8192)
            except IOError as exc:
                if exc.errno != errno.EAGAIN:
                    raise
                buf = None
            if not buf:
                return
            self._on_read(self._channel, buf, None)

    def start(self):
        self._channel.start_read(self._on_read)
        self._emitter.subscribe(self.write_evtype, self._on_write)
        self._emitter.subscribe(self.writelines_evtype, self._on_writelines)

    def stop(self):
        self._emitter.unsubscribe(self.write_evtype, self._on_write)
        self._emitter.unsubscribe(self.writelines_evtype, self._on_writelines)

        if not self._channel.closed:
            self._channel.close()

        self._process = None

    def __repr__(self):
        return '<Stream: evtype={0._evtype_prefix!r} active={0._channel.active!r}>'.format(self)


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

    def _setup_stdio(self):
        self._streams = [
            Stream(self._loop, self._emitter, self, 'stdin'),
            Stream(self._loop, self._emitter, self, 'stdout'),
            Stream(self._loop, self._emitter, self, 'stderr')
        ]
        self._stdio = [stream.stdio for stream in self._streams]

    @property
    def running(self):
        return self._running

    @property
    def os_pid(self):
        return self._process.pid if self._running else None

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
        self._process = pyuv.Process.spawn(self._loop, **kwargs)
        self._running = True

        # start redirecting IO
        for stream in self._streams:
            stream.start()

    def kill(self, signum):
        """Stop the process using SIGTERM."""
        if self._process is not None:
            try:
                self._process.kill(signum)
            except pyuv.error.ProcessError as exc:
                if exc.args[0] != pyuv.errno.UV_ESRCH:
                    raise

    def close(self):
        if self._process is not None:
            self._process.close()

    def _exit_cb(self, handle, exit_status, term_signal):
        self._running = False
        self._process = None
        handle.close()

        self._exit_status = exit_status
        self._term_signal = term_signal

        for stream in self._streams:
            stream.speculative_read()
            stream.stop()

        # handle the exit callback
        if self._on_exit_cb is not None:
            self._on_exit_cb(self, self._exit_status, self._term_signal)
