# conding: utf-8

from __future__ import absolute_import, unicode_literals

import uuid
import contextlib
import collections

import pytest
import pyuv

from .future import Future
from .manager import Manager
from .process import ProcessConfig
from .error import ProcessError

__all__ = ['pytest_configure', 'spawner']

DEFAULT_TIMEOUT = 5.0


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

    def pytest_sessionfinish(self, session, exitstatus):
        self._manager.stop()


class ProcessWaiter(object):

    def __init__(self, manager, cmd, env=None):
        self._manager = manager
        self._config = ProcessConfig(uuid.uuid4().hex, cmd, env=env)
        self._buffers = collections.defaultdict(list)
        self._future = Future()

    def _on_read(self, evtype, data):
        self._buffers[evtype[-1]].append(data['data'])

    def _on_exit(self, evtype, data):
        if data['exception']:
            self._future.set_exception(data['exception'])
        elif data['exit_status']:
            self._future.set_exception(
                ProcessError(self._config.cmd, data['exit_status'], data['term_signal']))
        else:
            self._future.set_result(b''.join(self._buffers['stdout']))

    def start(self):
        self._manager.load(self._config, start=False)
        self._manager.subscribe(self._config.read_evtype, self._on_read)
        self._manager.subscribe(self._config.exit_evtype, self._on_exit)
        self._manager.commit(self._config.name)

    def stop(self):
        self._manager.unsubscribe(self._config.exit_evtype, self._on_exit)
        self._manager.unsubscribe(self._config.read_evtype, self._on_read)
        self._manager.unload(self._config.name)

    def kill(self):
        pass

    def result(self, timeout=None):
        return self._future.result(timeout=timeout or DEFAULT_TIMEOUT)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


class SpawnerApi(object):

    def __init__(self, manager):
        self._manager = manager

    def check_output(self, cmd, env=None, timeout=None):
        with ProcessWaiter(self._manager, cmd, env) as watcher:
            return watcher.result(timeout)

    @contextlib.contextmanager
    def spawn(self, cmd, env=None, timeout=None):
        with ProcessWaiter(self._manager, cmd, env) as watcher:
            yield
            # kill process and wait when process will ended
            watcher.kill()
            watcher.result(timeout)


@pytest.fixture(scope="session")
def spawner(request):
    """Returns an API to access and control spawner."""
    return SpawnerApi(request.config._spawner_manager)
