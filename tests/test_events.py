# coding: utf-8

import pyuv

from pytest_spawner.events import EventEmitter

import pytest


@pytest.fixture
def loop():
    return pyuv.Loop.default_loop()


@pytest.yield_fixture
def emitter(loop):
    emitter = EventEmitter(loop)
    yield emitter
    emitter.stop()


def test_basic(loop, emitter):
    emitted = []

    def cb(ev):
        emitted.append(True)

    emitter.subscribe(("test", ), cb)
    emitter.publish(("test", ))
    loop.run()

    assert emitted == [True]


def test_publish_value(loop, emitter):
    emitted = []

    def cb(ev, val):
        emitted.append(val)

    emitter.subscribe(("test", ), cb)
    emitter.publish(("test", ), 1)
    emitter.publish(("test", ), 2)
    loop.run()

    assert emitted == [1, 2]

def test_publish_once(loop, emitter):
    emitted = []

    def cb(ev, val):
        emitted.append(val)

    emitter.subscribe(("test", ), cb, once=True)
    emitter.publish(("test", ), 1)
    loop.run()

    assert emitted == [1]


def test_multiple_listener(loop, emitter):
    emitted = []

    def cb1(ev, val):
        emitted.append((1, val))

    def cb2(ev, val):
        emitted.append((2, val))

    emitter.subscribe(("test", ), cb1)
    emitter.subscribe(("test", ), cb2)
    emitter.publish(("test", ), 1)
    loop.run()

    assert (1, 1) in emitted
    assert (2, 1) in emitted


def test_multipart(loop, emitter):
    emitted = []
    emitted2 = []

    def cb1(ev, val):
        emitted.append(val)

    def cb2(ev, val):
        emitted2.append(val)

    emitter.subscribe(("a", "b"), cb1)
    emitter.subscribe(("a", ), cb2)
    emitter.publish(("a", "b"), 1)
    emitter.publish(("a", ), 2)
    loop.run()

    assert emitted == [1]
    assert 1 in emitted2
    assert 2 in emitted2


def test_multipart2(loop, emitter):
    emitted = []

    def cb(ev, val):
        emitted.append(ev)

    emitter.subscribe(("a", "b"), cb)
    emitter.publish(("a", "b", "c"), 2)
    loop.run()

    assert emitted == [("a", "b", "c")]


def test_wildcard(loop, emitter):
    emitted = []
    emitted2 = []

    def cb(ev, val):
        emitted.append(val)

    def cb2(ev, val):
        emitted2.append(val)

    emitter.subscribe((), cb)
    emitter.subscribe(("a", "b"), cb2)

    emitter.publish(("a", "b"), 1)
    loop.run()

    assert emitted == [1]
    assert emitted2 == [1]


def test_unsubscribe(loop, emitter):
    emitted = []
    loop = pyuv.Loop.default_loop()

    def cb(ev, v):
        emitted.append(v)

    emitter.subscribe(("test", ), cb)
    emitter.publish(("test", ), "a")

    def unsubscribe(handle):
        emitter.unsubscribe(("test", ), cb)
        emitter.publish(("test", ), "b")

    t = pyuv.Timer(loop)
    t.start(unsubscribe, 0.2, 0.0)
    loop.run()

    assert emitted == ["a"]
