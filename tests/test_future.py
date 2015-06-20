# coding: utf-8
# pylint: disable=protected-access

import re
import time
import threading

import pytest

from pytest_spawner import future
from pytest_spawner.error import SpawnerError


def create_future(state=future.PENDING, exception=None, result=None):
    f = future.Future()
    f._state = state
    f._exception = exception
    f._result = result
    return f


PENDING_FUTURE = create_future(state=future.PENDING)
RUNNING_FUTURE = create_future(state=future.RUNNING)
CANCELLED_FUTURE = create_future(state=future.CANCELLED)
CANCELLED_AND_NOTIFIED_FUTURE = create_future(state=future.CANCELLED_AND_NOTIFIED)
EXCEPTION_FUTURE = create_future(state=future.FINISHED, exception=SpawnerError())
SUCCESSFUL_FUTURE = create_future(state=future.FINISHED, result=42)


def test_done_callback_with_result():
    callback_result = [None]
    def fn(callback_future):
        callback_result[0] = callback_future.result()

    f = future.Future()
    f.add_done_callback(fn)
    f.set_result(5)
    assert 5 == callback_result[0]


def test_done_callback_with_exception():
    callback_exception = [None]
    def fn(callback_future):
        callback_exception[0] = callback_future.exception()

    f = future.Future()
    f.add_done_callback(fn)
    f.set_exception(Exception('test'))
    assert ('test',) == callback_exception[0].args


def test_done_callback_with_cancel():
    was_cancelled = [None]
    def fn(callback_future):
        was_cancelled[0] = callback_future.cancelled()

    f = future.Future()
    f.add_done_callback(fn)
    assert f.cancel()
    assert was_cancelled[0]


def test_done_callback_raises(capsys):
    raising_was_called = [False]
    fn_was_called = [False]

    def raising_fn(callback_future):
        raising_was_called[0] = True
        raise Exception('doh!')

    def fn(callback_future):
        fn_was_called[0] = True

    f = future.Future()
    f.add_done_callback(raising_fn)
    f.add_done_callback(fn)
    f.set_result(5)
    _, stderr = capsys.readouterr()
    assert raising_was_called
    assert fn_was_called
    assert 'Exception: doh!' in stderr


def test_done_callback_already_successful():
    callback_result = [None]
    def fn(callback_future):
        callback_result[0] = callback_future.result()

    f = future.Future()
    f.set_result(5)
    f.add_done_callback(fn)
    assert 5 == callback_result[0]


def test_done_callback_already_failed():
    callback_exception = [None]
    def fn(callback_future):
        callback_exception[0] = callback_future.exception()

    f = future.Future()
    f.set_exception(Exception('test'))
    f.add_done_callback(fn)
    assert ('test',) == callback_exception[0].args


def test_done_callback_already_cancelled():
    was_cancelled = [None]
    def fn(callback_future):
        was_cancelled[0] = callback_future.cancelled()

    f = future.Future()
    assert f.cancel()
    f.add_done_callback(fn)
    assert was_cancelled[0]


def test_repr():
    assert re.match('<Future at 0x[0-9a-f]+ state=pending>', repr(PENDING_FUTURE))
    assert re.match('<Future at 0x[0-9a-f]+ state=running>', repr(RUNNING_FUTURE))
    assert re.match('<Future at 0x[0-9a-f]+ state=cancelled>', repr(CANCELLED_FUTURE))
    assert re.match('<Future at 0x[0-9a-f]+ state=cancelled>', repr(CANCELLED_AND_NOTIFIED_FUTURE))
    assert re.match('<Future at 0x[0-9a-f]+ state=finished raised SpawnerError>', repr(EXCEPTION_FUTURE))
    assert re.match('<Future at 0x[0-9a-f]+ state=finished returned int>', repr(SUCCESSFUL_FUTURE))


def test_cancel():
    f1 = create_future(state=future.PENDING)
    f2 = create_future(state=future.RUNNING)
    f3 = create_future(state=future.CANCELLED)
    f4 = create_future(state=future.CANCELLED_AND_NOTIFIED)
    f5 = create_future(state=future.FINISHED, exception=SpawnerError())
    f6 = create_future(state=future.FINISHED, result=5)

    assert f1.cancel()
    assert f1._state == future.CANCELLED

    assert not f2.cancel()
    assert f2._state == future.RUNNING

    assert f3.cancel()
    assert f3._state == future.CANCELLED

    assert f4.cancel()
    assert f4._state == future.CANCELLED_AND_NOTIFIED

    assert not f5.cancel()
    assert f5._state == future.FINISHED

    assert not f6.cancel()
    assert f6._state == future.FINISHED


@pytest.mark.parametrize('fut, expected', [
    (PENDING_FUTURE, False),
    (RUNNING_FUTURE, False),
    (CANCELLED_FUTURE, True),
    (CANCELLED_AND_NOTIFIED_FUTURE, True),
    (EXCEPTION_FUTURE, False),
    (SUCCESSFUL_FUTURE, False),
])
def test_cancelled(fut, expected):
    assert fut.cancelled() == expected


@pytest.mark.parametrize('fut, expected', [
    (PENDING_FUTURE, False),
    (RUNNING_FUTURE, False),
    (CANCELLED_FUTURE, True),
    (CANCELLED_AND_NOTIFIED_FUTURE, True),
    (EXCEPTION_FUTURE, True),
    (SUCCESSFUL_FUTURE, True),
])
def test_done(fut, expected):
    assert fut.done() == expected


def test_result_with_timeout():
    with pytest.raises(future.TimeoutError):
        PENDING_FUTURE.result(timeout=0)
    with pytest.raises(future.CancelledError):
        CANCELLED_FUTURE.result(timeout=0)
    with pytest.raises(future.CancelledError):
        CANCELLED_AND_NOTIFIED_FUTURE.result(timeout=0)
    with pytest.raises(future.CancelledError):
        CANCELLED_AND_NOTIFIED_FUTURE.result(timeout=0)
    with pytest.raises(SpawnerError):
        EXCEPTION_FUTURE.result(timeout=0)
    assert SUCCESSFUL_FUTURE.result(timeout=0) == 42


def test_result_with_success():
    # TODO(brian@sweetapp.com): This test is timing dependant.
    def notification():
        # Wait until the main thread is waiting for the result.
        time.sleep(0.1)
        f1.set_result(42)

    f1 = create_future(state=future.PENDING)
    t = threading.Thread(target=notification)
    t.start()

    assert f1.result(timeout=5) == 42


def test_result_with_cancel():
    # TODO(brian@sweetapp.com): This test is timing dependant.
    def notification():
        # Wait until the main thread is waiting for the result.
        time.sleep(0.1)
        f1.cancel()

    f1 = create_future(state=future.PENDING)
    t = threading.Thread(target=notification)
    t.start()

    with pytest.raises(future.CancelledError):
        f1.result(timeout=5)


def test_exception_with_timeout():
    with pytest.raises(future.TimeoutError):
        PENDING_FUTURE.exception(timeout=0)
    with pytest.raises(future.TimeoutError):
        RUNNING_FUTURE.exception(timeout=0)
    with pytest.raises(future.CancelledError):
        CANCELLED_FUTURE.exception(timeout=0)
    with pytest.raises(future.CancelledError):
        CANCELLED_AND_NOTIFIED_FUTURE.exception(timeout=0)
    assert isinstance(EXCEPTION_FUTURE.exception(timeout=0), SpawnerError)
    assert SUCCESSFUL_FUTURE.exception(timeout=0) is None


def test_exception_with_success():
    def notification():
        # Wait until the main thread is waiting for the exception.
        time.sleep(0.1)
        with f1._condition:
            f1._state = future.FINISHED
            f1._exception = SpawnerError()
            f1._condition.notify_all()

    f1 = create_future(state=future.PENDING)
    t = threading.Thread(target=notification)
    t.start()

    assert isinstance(f1.exception(timeout=5), SpawnerError)

