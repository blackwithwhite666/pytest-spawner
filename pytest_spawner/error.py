# coding: utf-8


class ProcessError(Exception):
    pass


class ProcessNotFound(ProcessError):
    pass


class ProcessConflict(ProcessError):
    pass
