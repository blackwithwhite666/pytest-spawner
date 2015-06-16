# conding: utf-8

from __future__ import absolute_import, unicode_literals

from .manager import Manager


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


class SpawnerFuncArg(object):

    def __init__(self, manager):
        self._manager = manager

    def load(self, config, **kwargs):
        self._manager.load(config, **kwargs)

    def commit(self, name):
        self._manager.commit(name)


def pytest_funcarg__spawner(request):
    """Returns a funcarg to access and control spawner."""
    return SpawnerFuncArg(request._pyfuncitem.spawner_manager)
