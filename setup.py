#!/usr/bin/env python
import io
import os
import re

from setuptools import setup, find_packages


def _read_text_file(file_name):
    file_path = os.path.join(os.path.dirname(__file__), file_name)
    with io.open(file_path, encoding='utf-8') as f_stream:
        return f_stream.read()


def _get_version():
    return re.search("__version__\s*=\s*'([^']+)'\s*",
                     _read_text_file('pytest_spawner/__init__.py')).group(1)


setup(name='pytest-spawner',
      version=_get_version(),
      description='py.test plugin to spawn process and communicate with them.',
      long_description=_read_text_file('README.rst'),
      author='Dmitriy Lipin',
      author_email='dldmitry@yandex-team.ru',
      url='https://git.qe-infra.yandex-team.ru/users/dldmitry/repos/pytest-spawner/browse',
      packages=find_packages('pytest_spawner'),
      install_requires=['py>=1.1.1', 'pyuv>=1.0.0'],
      entry_points={'pytest11': ['pytest_spawner = pytest_spawner.plugin']},
      license='MIT License',
      zip_safe=False,
      keywords='py.test pytest',
      classifiers=['Development Status :: 4 - Beta',
                   'Intended Audience :: Developers',
                   'License :: OSI Approved :: MIT License',
                   'Operating System :: OS Independent',
                   'Programming Language :: Python',
                   'Programming Language :: Python :: 2.7',
                   'Programming Language :: Python :: 3.4',
                   'Programming Language :: Python :: Implementation :: CPython',
                   'Topic :: Software Development :: Testing'])
