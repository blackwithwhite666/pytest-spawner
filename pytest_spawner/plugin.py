# conding: utf-8

from __future__ import absolute_import, unicode_literals

import os
import contextlib
import collections
import logging

import pytest
import pyuv

from .future import Future
from .manager import Manager
from .process import ProcessConfig
from .string_buffer import StringBuffer
from .error import ProcessError

__all__ = ['pytest_configure', 'spawner']

DEFAULT_TIMEOUT = 15.0


def pytest_configure(config):
    """Always register the spawner plugin with py.test or tests can't
    find the fixture function.
    """
    config.pluginmanager.register(SpawnerPlugin(config), '_spawner')


class SpawnerPlugin(object):
    """Create process registry that should spawn new processes and kill existing."""

    def __init__(self, config):
        self._manager = Manager()

    def pytest_configure(self, config):
        config._spawner_manager = self._manager

    def pytest_sessionstart(self, session):
        self._manager.start()

    def pytest_unconfigure(self, config):
        if self._manager.started:
            self._manager.stop()


class ProcessWatcher(object):

    def __init__(self, manager, name, cmd, **kwargs):
        self._manager = manager
        self._buffers = collections.defaultdict(StringBuffer)
        self._future = Future()
        self._logger = logging.getLogger('spawner.%s' % name)

        self._redirect_stdout = False
        self._redirect_stdout = kwargs.pop('redirect_stdout', False)
        if self._redirect_stdout:
            assert not kwargs.get('capture_stdout'), 'can\'t use redirect_stdout with capture_stdout'
            kwargs['capture_stdout'] = True

        self._redirect_stderr = False
        self._redirect_stderr = kwargs.pop('redirect_stderr', False)
        if self._redirect_stderr:
            assert not kwargs.get('capture_stderr'), 'can\'t use redirect_stderr with capture_stderr'
            kwargs['capture_stderr'] = True

        self._ignore_exit_status = kwargs.pop('ignore_exit_status', False)

        self._config = ProcessConfig(name, cmd, **kwargs)
        self._closed = False

    def _log_line(self, line, level=logging.INFO):
        line = line.strip()
        if line:
            self._logger.log(level, line)

    def _buffer_to_log(self, buf, level=logging.INFO):
        while True:
            line = buf.read_until('\n')
            if line is None:
                return
            self._log_line(line, level)

    def _on_read(self, evtype, data):
        buf = self._buffers[evtype[-1]]
        buf.feed(data['data'])
        if self._redirect_stdout and evtype[-1] == 'stdout':
            self._buffer_to_log(buf)
        elif self._redirect_stderr and evtype[-1] == 'stderr':
            self._buffer_to_log(buf, logging.ERROR)

    def _on_exit(self, evtype, data):
        stdout_data = self._buffers['stdout'].read_all()
        stderr_data = self._buffers['stderr'].read_all()

        if self._redirect_stdout:
            self._log_line(stdout_data)
        if self._redirect_stderr:
            self._log_line(stderr_data, logging.ERROR)

        if data['exception']:
            self._future.set_exception(data['exception'])
        elif data['exit_status'] and not self._ignore_exit_status:
            self._future.set_exception(
                ProcessError(self._config.cmd, data['exit_status'], data['term_signal']))
        else:
            self._future.set_result({
                'stdout': stdout_data if not self._redirect_stdout else None,
                'stderr': stderr_data if not self._redirect_stderr else None,
                'exit_status': data['exit_status']
            })

        if self._closed:
            self._manager.unsubscribe(self._config.exit_evtype, self._on_exit)
            self._manager.unsubscribe(self._config.read_evtype, self._on_read)

    def start(self):
        self._manager.load(self._config, start=False)
        self._manager.commit(self._config.name)

    def stop(self):
        self._manager.unload(self._config.name)

    def restart(self):
        self.stop()
        self.start()
        # reset future
        self._future.cancel()
        self._future = Future()

    def result(self, timeout=None):
        return self._future.result(timeout=timeout or DEFAULT_TIMEOUT)

    def __enter__(self):
        assert not self._closed, "watcher already closed"
        self._manager.subscribe(self._config.read_evtype, self._on_read)
        self._manager.subscribe(self._config.exit_evtype, self._on_exit)
        self.start()
        return self

    def __exit__(self, *args):
        self._closed = True
        self.stop()


class SpawnerApi(object):

    def __init__(self, manager):
        self._manager = manager

    def create(self, name, cmd, args=None, **kwargs):
        return ProcessWatcher(self._manager, name, cmd, args=args, **kwargs)

    def check(self, cmd, args=None, **kwargs):
        timeout = kwargs.pop("timeout", None)
        name = os.path.basename(cmd)
        assert not self._manager.exists(name), "process with name %s already exists" % name
        with self.create(name, cmd, args=args, **kwargs) as watcher:
            return watcher.result(timeout)

    def check_call(self, cmd, args=None, **kwargs):
        return self.check(cmd, args=args, redirect_stdout=True, redirect_stderr=True, **kwargs)['exit_status']

    def check_output(self, cmd, args=None, **kwargs):
        return self.check(cmd, args=args, capture_stdout=True, redirect_stderr=True, **kwargs)['stdout']

    @contextlib.contextmanager
    def spawn(self, name, cmd, args=None, **kwargs):
        timeout = kwargs.pop("timeout", None)
        watcher = self.create(name, cmd, args=args, redirect_stdout=True, redirect_stderr=True, **kwargs)
        with watcher:
            yield watcher
        # check for result code
        watcher.result(timeout)


@pytest.fixture(scope="session")
def spawner(request):
    """Returns an API to access and control spawner."""
    return SpawnerApi(request.config._spawner_manager)
