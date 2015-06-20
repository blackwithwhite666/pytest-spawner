# conding: utf-8

from __future__ import absolute_import, unicode_literals

import collections

import pyuv

from .future import Future
from .manager import Manager
from .process import ProcessConfig
from .error import ProcessError


def pytest_configure(config):
    """Always register the spawner plugin with py.test or tests can't
    find the fixture function.
    """
    config.pluginmanager.register(SpawnerPlugin(config), '_spawner')


class SpawnerPlugin(object):
    """Create process registry that should spawn new processes and kill existing."""

    def __init__(self, config):
        self._manager = Manager()

    def pytest_runtest_setup(self, item):
        """Start processes for this test."""
        item.spawner_manager = self._manager

    def pytest_sessionstart(self, session):
        self._manager.start()

    def pytest_sessionfinish(self, session, exitstatus):
        self._manager.stop()


class ProcessWaiter(object):

    def __init__(self, manager, name, cmd, env=None):
        self._manager = manager
        self._config = ProcessConfig(name, cmd, env=env)
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

    def _start(self):
        self._manager.load(self._config, start=False)
        self._manager.subscribe(self._config.read_evtype, self._on_read)
        self._manager.subscribe(self._config.exit_evtype, self._on_exit)
        self._manager.commit(self._config.name)

    def _stop(self):
        self._manager.unsubscribe(self._config.exit_evtype, self._on_exit)
        self._manager.unsubscribe(self._config.read_evtype, self._on_read)
        self._manager.unload(self._config.name)

    def result(self, timeout=None):
        return self._future.result(timeout=timeout)

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, *args):
        self._stop()


class SpawnerFuncArg(object):

    def __init__(self, manager):
        self._manager = manager

    def check_output(self, cmd, env=None, timeout=None):
        with ProcessWaiter(self._manager, 'test', cmd, env) as watcher:
            return watcher.result(timeout)


def pytest_funcarg__spawner(request):
    """Returns a funcarg to access and control spawner."""
    return SpawnerFuncArg(request._pyfuncitem.spawner_manager)
