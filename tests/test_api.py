# coding: utf-8

def test_check_output(spawner):
    assert spawner.check_output('echo test', timeout=5).strip() == b'test'

