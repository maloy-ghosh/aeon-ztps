# Copyright 2014-present, Apstra, Inc. All rights reserved.
#
# This source code is licensed under End User License Agreement found in the
# LICENSE file at http://www.apstra.com/community/eula

import re
import logging

from aeon import exceptions
from aeon.utils.probe import probe
from aeon.cros.connector import Connector


__all__ = ['Device']

_PROGNAME = 'cros-bootstrap-device'
_PROGVER = '0.0.1'
_OS_NAME = 'cros'

_DEFAULTS = {
    'logfile': "/tmp/cros.log",
}

def setup_logging(logname, logfile, target):
    log = logging.getLogger(name=logname)
    log.setLevel(logging.INFO)

    fmt = logging.Formatter(
        '%(asctime)s:%(levelname)s:{target}:%(message)s'
        .format(target=target))

    handler = logging.FileHandler(logfile) if logfile else logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    log.addHandler(handler)

    return log



class Device(object):
    OS_NAME = 'cros'
    DEFAULT_PROBE_TIMEOUT = 3
    DEFAULT_USER = 'ztp'
    DEFAULT_PASSWD = 'Ztp@1234'

    def __init__(self, target, **kwargs):
        """
        :param target: hostname or ipaddr of target device
        :param kwargs:
            'user' : login user-name, defaults to "ztp"
            'passwd': login password, defaults to "Ztp@1234
        """
        self.target = target
        self.loghandle = kwargs.get('loghandle', None)

        if (self.loghandle == None):
            self.loghandle = setup_logging(logname=_PROGNAME,
                           logfile=_DEFAULTS['logfile'],
                           target=target)

        self.api = Connector(hostname=self.target,
                             user=kwargs.get('user', self.DEFAULT_USER),
                             passwd=kwargs.get('passwd', self.DEFAULT_PASSWD))

        self.facts = {}

        if 'no_probe' not in kwargs:
            self.probe(**kwargs)

        if 'no_gather_facts' not in kwargs:
            self.gather_facts()


    def probe(self, **kwargs):
        timeout = kwargs.get('timeout') or self.DEFAULT_PROBE_TIMEOUT
        ok, elapsed = probe(self.target, protocol='ssh', timeout=timeout)
        if not ok:
            raise exceptions.ProbeError()

    def _serial_from_mac(self, macaddr):
        return macaddr.replace(':', '').upper()


    def gather_facts(self):

        facts = self.facts
        facts['os_name'] = self.OS_NAME

        self.loghandle.info("Gathering facts");

        good, got = self.api.execute([
            'show version'
        ])

        version = got[0]['stdout']
        decoded = {}

        for line in version.splitlines():
            if line.strip():
                splitted = line.split(":")
                tag = splitted[0].strip()
                value = ":".join(splitted[1:]).strip()

                decoded[tag] = value


        #facts['fqdn'] = decoded["Host"]
        facts['hostname'] = decoded["Host"]
        facts['os_version'] = decoded["Software Version"]
        facts['vendor'] = "C-DOT"
        if decoded['Serial Num'] != "n/a":
            facts['serial_number'] = decoded['Serial Num']
        else:
            facts['serial_number'] = self._serial_from_mac(decoded['System MAC'])


        facts['hw_model'] = decoded['Model']

        self.loghandle.info("Facts: {}".format(facts))
