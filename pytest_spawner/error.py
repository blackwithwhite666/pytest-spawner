# coding: utf-8

from __future__ import absolute_import, unicode_literals


class SpawnerError(Exception):
    pass


class FutureError(SpawnerError):
    pass


class CancelledError(FutureError):
    """The Future was cancelled."""
    pass


class TimeoutError(FutureError):
    """The operation exceeded the given deadline."""
    pass


class StateError(SpawnerError):
    pass


class StateNotFound(StateError):
    pass


class StateConflict(StateError):
    pass


class ProcessError(SpawnerError):

    def __init__(self, cmd, exit_status, term_signal):
        self.cmd = cmd
        self.exit_status = exit_status
        self.term_signal = term_signal
        super(ProcessError, self).__init__(
            'Command %r returned non-zero exit status %d' % (self.cmd, self.exit_status))
