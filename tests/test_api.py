# coding: utf-8


def test_check_output(spawner):
    assert spawner.check_output('echo test').strip() == b'test'


def test_check_call(spawner):
    assert spawner.check_call('sh -c "exit 0"') == 0
