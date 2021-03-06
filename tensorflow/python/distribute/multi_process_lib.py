# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Library for multi-process testing."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import multiprocessing
import os
import sys
import unittest
from absl import app

from tensorflow.python.eager import test


def _is_enabled():
  return sys.platform != 'win32'


class _AbslProcess:
  """A process that runs using absl.app.run."""

  def __init__(self, *args, **kwargs):
    super(_AbslProcess, self).__init__(*args, **kwargs)
    # Monkey-patch that is carried over into the spawned process by pickle.
    self._run_impl = getattr(self, 'run')
    self.run = self._run_with_absl

  def _run_with_absl(self):
    app.run(lambda _: self._run_impl())


if _is_enabled():

  class AbslForkServerProcess(_AbslProcess,
                              multiprocessing.context.ForkServerProcess):
    """An absl-compatible Forkserver process.

    Note: Forkserver is not available in windows.
    """

  class AbslForkServerContext(multiprocessing.context.ForkServerContext):
    _name = 'absl_forkserver'
    Process = AbslForkServerProcess  # pylint: disable=invalid-name

  multiprocessing = AbslForkServerContext()
  Process = multiprocessing.Process

else:

  class Process(object):
    """A process that skips test (until windows is supported)."""

    def __init__(self, *args, **kwargs):
      del args, kwargs
      raise unittest.SkipTest(
          'TODO(b/150264776): Windows is not supported in MultiProcessRunner.')


_test_main_called = False


def _set_spawn_exe_path():
  """Set the path to the executable for spawned processes.

  This utility searches for the binary the parent process is using, and sets
  the executable of multiprocessing's context accordingly.

  Raises:
    RuntimeError: If the binary path cannot be determined.
  """
  # TODO(b/150264776): This does not work with Windows. Find a solution.
  if sys.argv[0].endswith('.py'):
    # If all we have is a python module path, we'll need to make a guess for
    # the actual executable path. Since the binary path may correspond to the
    # parent's path of the python module, we are making guesses by reducing
    # directories one at a time. E.g.,
    # tensorflow/python/some/path/my_test.py
    # -> tensorflow/python/some/path/my_test
    # -> tensorflow/python/some/my_test
    # -> tensorflow/python/my_test
    path_to_use = None
    guess_path = sys.argv[0][:-3]
    guess_path = guess_path.split(os.sep)
    for path_reduction in range(-1, -len(guess_path), -1):
      possible_path = os.sep.join(guess_path[:path_reduction] +
                                  [guess_path[-1]])
      if os.access(possible_path, os.X_OK):
        path_to_use = possible_path
        break
      # The binary can possibly have _gpu suffix.
      possible_path += '_gpu'
      if os.access(possible_path, os.X_OK):
        path_to_use = possible_path
        break
    if path_to_use is None:
      raise RuntimeError('Cannot determine binary path')
    sys.argv[0] = path_to_use
  # Note that this sets the executable for *all* contexts.
  multiprocessing.get_context().set_executable(sys.argv[0])


def _if_spawn_run_and_exit():
  """If spawned process, run requested spawn task and exit. Else a no-op."""

  # `multiprocessing` module passes a script "from multiprocessing.x import y"
  # to subprocess, followed by a main function call. We use this to tell if
  # the process is spawned. Examples of x are "forkserver" or
  # "semaphore_tracker".
  is_spawned = ('-c' in sys.argv[1:] and
                sys.argv[sys.argv.index('-c') +
                         1].startswith('from multiprocessing.'))

  if not is_spawned:
    return
  cmd = sys.argv[sys.argv.index('-c') + 1]
  # As a subprocess, we disregarding all other interpreter command line
  # arguments.
  sys.argv = sys.argv[0:1]

  # Run the specified command - this is expected to be one of:
  # 1. Spawn the process for semaphore tracker.
  # 2. Spawn the initial process for forkserver.
  # 3. Spawn any process as requested by the "spawn" method.
  exec(cmd)  # pylint: disable=exec-used
  sys.exit(0)  # Semaphore tracker doesn't explicitly sys.exit.


def test_main():
  """Main function to be called within `__main__` of a test file."""
  global _test_main_called
  _test_main_called = True

  os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'

  if _is_enabled():
    _set_spawn_exe_path()
    _if_spawn_run_and_exit()

  # Only runs test.main() if not spawned process.
  test.main()


def initialized():
  """Returns whether the module is initialized."""
  return _test_main_called
