# Copyright 2016 Google Inc. All Rights Reserved.
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

"""Command line interface to subpar compiler"""

import argparse
import io
import os
import re

from subpar.compiler import error
from subpar.compiler import python_archive


def bool_from_string(raw_value):
    """Parse a boolean command line argument value"""
    if raw_value == 'True':
        return True
    elif raw_value == 'False':
        return False
    else:
        raise argparse.ArgumentTypeError(
            'Value must be True or False, got %r instead.' % raw_value)


def make_command_line_parser():
    """Return an object that can parse this program's command line"""
    parser = argparse.ArgumentParser(
        description='Subpar Python Executable Builder')

    parser.add_argument(
        'main_filename',
        help='Python source file to use as main entry point')

    parser.add_argument(
        '--manifest_file',
        help='File listing all files to be included in this parfile. This is ' +
        'typically generated by bazel in a target\'s .runfiles_manifest file.',
        required=True)
    parser.add_argument(
        '--manifest_root',
        help='Root directory of all relative paths in manifest file.',
        default=os.getcwd())
    parser.add_argument(
        '--output_par',
        help='Filename of generated par file.',
        required=True)
    parser.add_argument(
        '--stub_file',
        help='Read imports and interpreter path from the specified stub file',
        required=True)
    parser.add_argument(
        '--interpreter',
        help='Interpreter to use instead of determining it from the stub file')
    # The default timestamp is "Jan 1 1980 00:00:00 utc", which is the
    # earliest time that can be stored in a zip file.
    #
    # "Seconds since Unix epoch" was chosen to be compatible with
    # the SOURCE_DATE_EPOCH standard
    #
    # Numeric value is from running this:
    #   "date --date='Jan 1 1980 00:00:00 utc' --utc +%s"
    parser.add_argument(
        '--timestamp',
        help='Timestamp (in seconds since Unix epoch) for all stored files',
        type=int,
        default=315532800,
        )
    # See
    # http://setuptools.readthedocs.io/en/latest/setuptools.html#setting-the-zip-safe-flag
    # for background and explanation.
    parser.add_argument(
        '--zip_safe',
        help='Safe to import modules and access datafiles straight from zip ' +
        'archive?  If False, all files will be extracted to a temporary ' +
        'directory at the start of execution.',
        type=bool_from_string,
        required=True)
    parser.add_argument(
        '--import_root',
        help='Path to add to sys.path, may be repeated to provide multiple roots.',
        action='append',
        default=[],
        dest='import_roots')
    return parser


def parse_stub(stub_filename):
    """Parse interpreter path from a py_binary() stub.

    We assume the stub is utf-8 encoded.

    TODO(bazelbuild/bazel#7805): Remove this once we can access the py_runtime from Starlark.

    Returns path to Python interpreter
    """

    # Find the interpreter
    interpreter_regex = re.compile(r'''^PYTHON_BINARY = '([^']*)'$''')
    interpreter = None
    with io.open(stub_filename, 'rt', encoding='utf8') as stub_file:
        for line in stub_file:
            interpreter_match = interpreter_regex.match(line)
            if interpreter_match:
                interpreter = interpreter_match.group(1)
    if not interpreter:
        raise error.Error('Failed to parse stub file [%s]' % stub_filename)

    # Determine the Python interpreter, checking for default toolchain.
    #
    # This somewhat mirrors the logic in python_stub_template.txt, but we don't support
    # relative paths (i.e., in-workspace interpreters). This is because the interpreter
    # will be used in the .par file's shebang, and putting a relative path in a shebang
    # is extremely brittle and non-relocatable. (The reason the standard py_binary rule
    # can use an in-workspace interpreter is that its stub script runs in a separate
    # process and has a shebang referencing the system interpreter). As a special case,
    # if the Python target is using the autodetecting Python toolchain, which is
    # technically an in-workspace runtime, we rewrite it to "/usr/bin/env python[2|3]"
    # rather than fail.
    if interpreter.startswith('//'):
        raise error.Error('Python interpreter must not be a label [%s]' %
                          stub_filename)
    elif interpreter.startswith('/'):
        pass
    elif interpreter == 'bazel_tools/tools/python/py3wrapper.sh': # Default toolchain
        # Replace default toolchain python3 wrapper with default python3 on path
        interpreter = '/usr/bin/env python3'
    elif interpreter == 'bazel_tools/tools/python/py2wrapper.sh': # Default toolchain
        # Replace default toolchain python2 wrapper with default python2 on path
        interpreter = '/usr/bin/env python2'
    elif '/' in interpreter:
        raise error.Error(
            'par files require a Python runtime that is ' +
            'installed on the system, not defined inside the workspace. Use ' +
            'a `py_runtime` with an absolute path, not a label.')
    else:
        interpreter = '/usr/bin/env %s' % interpreter

    return interpreter


def main(argv):
    """Command line interface to Subpar"""
    parser = make_command_line_parser()
    args = parser.parse_args(argv[1:])

    # Parse interpreter from stub file that's not available in Starlark
    interpreter = parse_stub(args.stub_file)

    if args.interpreter:
        interpreter = args.interpreter

    par = python_archive.PythonArchive(
        main_filename=args.main_filename,
        import_roots=args.import_roots,
        interpreter=interpreter,
        output_filename=args.output_par,
        manifest_filename=args.manifest_file,
        manifest_root=args.manifest_root,
        timestamp=args.timestamp,
        zip_safe=args.zip_safe,
    )
    par.create()
