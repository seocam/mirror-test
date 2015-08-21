#!/usr/bin/env python

import importlib
import inspect
import logging
import os
import sys

from django.core.management.base import BaseCommand
from django.conf import settings

from colab.proxy.utils.proxy_data_api import ProxyDataAPI


class Command(BaseCommand):
    help = "Import proxy data into colab database"

    lock_file = settings.IMPORT_DATA_LOCK_FILE

    def handle(self, *args, **kwargs):
        if os.path.exists(self.lock_file):
            print(("This script is already running. "
                   "(If your are sure it's not please "
                   "delete the lock file in {}')").format(self.lock_file))
            sys.exit(1)

        if not os.path.exists(os.path.dirname(self.lock_file)):
            os.mkdir(os.path.dirname(self.lock_file), 0755)

        run_lock = file(self.lock_file, 'w')
        run_lock.close()

        try:
            self.run()
        except Exception as e:
            logging.exception(e)
            raise
        finally:
            os.remove(self.lock_file)

    def run(self):
        print "Executing extraction command..."

        for module_name in settings.PROXIED_APPS.keys():
            module_path = 'colab.proxy.{}.data_api'.format(module_name)
            module = importlib.import_module(module_path)

            for module_item_name in dir(module):
                module_item = getattr(module, module_item_name)
                if not inspect.isclass(module_item):
                    continue
                if issubclass(module_item, ProxyDataAPI):
                    if module_item != ProxyDataAPI:
                        api = module_item()
                        api.fetch_data()
                        break
