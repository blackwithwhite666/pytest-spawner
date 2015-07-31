# coding: utf-8

import re

import pytest

from pytest_spawner.string_buffer import StringBuffer


def test_read():
    buf = StringBuffer()
    buf.feed(b'hello world')
    data = buf.read(5)
    assert data == b'hello'
    data = buf.read(6)
    assert data == b' world'
    data = buf.read(100)
    assert data is None


def test_read_all():
    buf = StringBuffer()
    buf.feed(b'hello')
    buf.feed(b' ')
    buf.feed(b'world')
    assert buf.read_all() == b'hello world'
    assert buf.read(100) is None


def test_read_until():
    buf = StringBuffer()
    buf.feed(b'hello\nworld\n')
    data = buf.read_until(b'\n')
    assert data == b'hello\n'
    data = buf.read_until(b'\n')
    assert data == b'world\n'
    data = buf.read_until(b'\n')
    assert data is None

def test_read_until_regex():
    regex = re.compile(b'~~')
    buf = StringBuffer()
    buf.feed(b'hello~~world~~')
    data = buf.read_until_regex(regex)
    assert data == b'hello~~'
    data = buf.read_until_regex(regex)
    assert data == b'world~~'
    data = buf.read_until_regex(regex)
    assert data == None


def test_clear():
    buf = StringBuffer()
    buf.feed(b'hello world')
    buf.clear()
    data = buf.read(5)
    assert data is None


def test_close():
    buf = StringBuffer()
    buf.feed(b'hello world')
    buf.close()
    assert buf.closed
    with pytest.raises(ValueError):
        buf.read(5)

