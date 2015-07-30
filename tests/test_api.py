# coding: utf-8

import pytest

from pytest_spawner.error import ProcessError


def test_check_output(spawner):
    assert spawner.check_output('echo test').strip() == b'test'
    with pytest.raises(ProcessError):
        spawner.check_output('sh -c "exit 1"')


def test_check_call(spawner):
    assert spawner.check_call('sh -c "exit 0"') == 0
    with pytest.raises(ProcessError):
        spawner.check_call('sh -c "exit 1"')


def test_spawn(spawner):
    with spawner.spawn("bash", "bash -i"):
        pass
