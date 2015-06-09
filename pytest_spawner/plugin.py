# conding: utf-8

from __future__ import absolute_import, unicode_literals


def pytest_configure(config):
    """Always register the spawner plugin with py.test or tests can't
    find the fixture function.
    """
    config.pluginmanager.register(SpawnerPlugin(config), '_spawner')


class SpawnerPlugin(object):
    """Create process registry that should spawn new processes and kill existing."""

    def __init__(self, config):
        pass

    def pytest_runtest_setup(self, item):
        """Start processes for this test."""

