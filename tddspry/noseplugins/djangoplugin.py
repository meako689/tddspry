"""
"""

import logging
import os
import sys

from nose.plugins.base import Plugin
from nose.util import getfilename, resolve_name, skip_pattern, _ls_tree_lines


__all__ = ('DjangoPlugin', )


log = logging.getLogger(__name__)


class DjangoPlugin(Plugin):
    """
    Run nosetests for Django (<= 1.1) projects or apps. You need to specify
    settings of your project or plugin tries to auto-load from current or
    child directories.
    """
    error_dir = None
    name = 'django'
    settings = None
    verbosity = 1

    def begin(self):
        from django.conf import settings
        from django.core.handlers.wsgi import WSGIHandler
        from django.core.servers.basehttp import AdminMediaHandler
        from django.db import connection
        from django.test.simple import TEST_MODULE
        from django.test.utils import setup_test_environment

        from tddspry.django.settings import IP, PORT

        from twill import add_wsgi_intercept

        def ispackage(module):
            return module.__file__.rstrip('co').endswith('__init__.py')

        def load_tests(name):
            module = resolve_name(name)
            log.debug('Load tests for: %s', module)

            if not hasattr(module, '__file__') or not ispackage(module):
                return

            childs = list(_ls_tree_lines(os.path.dirname(module.__file__),
                                         skip_pattern,
                                         '', '', '', ''))

            for child in list(childs):
                if not child.endswith('.py') or child == '__init__.py':
                    continue

                tests = name + '.' + child[:-3]
                load_tests(tests)

        log.debug('DjangoPlugin start')

        # Find to Django models in tests modules for each of ``INSTALLED_APPS``
        for label in settings.INSTALLED_APPS:
            tests = label + '.' + TEST_MODULE
            log.debug('Tests module: %s', tests)

            try:
                load_tests(tests)
            except (AttributeError, ImportError):
                pass

        # Setup Django test environment
        setup_test_environment()

        # Create Django test database
        self.old_database_name = settings.DATABASE_NAME
        connection.creation.create_test_db(self.verbosity, autoclobber=True)

        # Setup Twill for testing with Django
        app = AdminMediaHandler(WSGIHandler())
        add_wsgi_intercept(IP, PORT, lambda: app)

    def configure(self, options, config):
        Plugin.configure(self, options, config)

        # Check that Django and twill libraries available in this system
        if self.enabled:
            for lib in ('Django', 'twill'):
                try:
                    __import__(lib.lower())
                except ImportError, e:
                    log.error('%s not available: %s' % (lib, e))
                    self.enabled = False
                    return

        # Get user defined options
        self.error_dir = options.error_dir
        self.settings = options.settings
        self.verbosity = options.verbosity

        # Try to load Django project settings
        self.load_settings(self.settings)

        # Make sure that ``TWILL_ERROR_DIR`` set to ``os.environ`` if needed
        if self.error_dir:
            os.environ['TWILL_ERROR_DIR'] = self.error_dir

    def error(self, settings, dirname, subdirs=None):
        if settings is not None:
            sys.stderr.write(
                "Error: Can't find the module %r in the current work " \
                "directory %r.\n(If the file settings.py does indeed exist, " \
                "it's causing an ImportError somehow.)\n" % (settings, dirname)
            )
        else:
            sys.stderr.write(
                "Error: Can't find the file 'settings.py' in the current " \
                "work directory %r and all subdirectories %r. It appears " \
                "you've customized things.\nYou'll have to run `nosetests " \
                "--with-django` passing it your settings module.\n(If the " \
                "file settings.py does indeed exist, it's causing an " \
                "ImportError somehow.)\n" % (dirname, subdirs)
            )
        sys.exit(1)

    def fake_import(self, package):
        filename = getfilename(package)
        if not filename:
            raise ImportError
        return filename

    def load_settings(self, settings=None):
        old_settings = settings

        dirname = os.getcwd()
        sys.path.append(dirname)

        childs = os.listdir(dirname)
        childs.sort()

        subdirs = []

        for name in childs:
            if name[0] == '.':
                continue

            if os.path.isdir(os.path.join(dirname, name)):
                subdirs.append(name)

        try:
            settings = old_settings or 'settings'

            try:
                self.fake_import(settings)
            except ImportError:
                if old_settings is not None:
                    self.error(old_settings, dirname)

                settings = os.path.basename(dirname) + '.settings'

                try:
                    self.fake_import(settings)
                except ImportError:
                    imported = False

                    for subdir in subdirs:
                        settings = subdir + '.settings'

                        try:
                            self.fake_import(settings)
                        except ImportError:
                            pass
                        else:
                            imported = True
                            break

                    if not imported:
                        raise ImportError
        except ImportError:
            self.error(None, dirname, subdirs)

        os.environ['DJANGO_SETTINGS_MODULE'] = settings

    def options(self, parser, env=None):
        env = env or os.environ
        Plugin.options(self, parser, env)

        parser.add_option('--django-settings', action='store',
                          default=env.get('DJANGO_SETTINGS_MODULE'),
                          dest='settings', help='Settings module of your ' \
                          'Django project to test. [DJANGO_SETTINGS_MODULE]')
        parser.add_option('--django-verbosity', action='store',
                          default=1, dest='verbosity', type='int',
                          help='Django verbosity level.')
        parser.add_option('--twill-error-dir', action='store',
                          default=env.get('TWILL_ERROR_DIR'), dest='error_dir',
                          help='If `TwillAssertionError` raised store all ' \
                          'output in this directory. [TWILL_ERROR_DIR]')

    def report(self, stream):
        from django.db import connection
        from django.test.utils import teardown_test_environment

        log.debug('DjangoPlugin report')

        # Destroy Django test database
        connection.creation.destroy_test_db(self.old_database_name,
                                            self.verbosity)

        # Teardown Django test environment
        teardown_test_environment()
