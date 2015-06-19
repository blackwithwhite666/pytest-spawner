# conding: utf-8

from __future__ import absolute_import, unicode_literals

import collections

from .future import Future
from .manager import Manager
from .process import ProcessConfig


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
        self._pid = None

    def _on_read(self, evtype, data):
        self._buffers[evtype[-1]].append(data['data'])

    def _on_exit(self, evtype, data):
        self._future.set_result(b''.join(self._buffers['stdout']))

    def start(self):
        self._manager.load(self._config, start=False)
        self._pid = self._manager.commit(self._config.name)
        self._manager.subscribe(('proc', self._pid, 'read'), self._on_read)
        self._manager.subscribe(('proc', self._pid, 'exit'), self._on_exit)

    def stop(self):
        self._manager.unsubscribe(('proc', self._pid, 'exit'), self._on_exit)
        self._manager.unsubscribe(('proc', self._pid, 'read'), self._on_read)
        self._manager.unload(self._config.name)

    def result(self, timeout=None):
        return self._future.result(timeout=timeout)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


class SpawnerFuncArg(object):

    def __init__(self, manager):
        self._manager = manager

    def check_output(self, cmd, env=None, timeout=None):
        with ProcessWaiter(self._manager, 'test', cmd, env) as watcher:
            return watcher.result(timeout)


def pytest_funcarg__spawner(request):
    """Returns a funcarg to access and control spawner."""
    return SpawnerFuncArg(request._pyfuncitem.spawner_manager)
