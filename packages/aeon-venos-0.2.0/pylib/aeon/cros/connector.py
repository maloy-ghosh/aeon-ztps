# -*- coding: future_fstrings -*-


# Copyright 2014-present, Apstra, Inc. All rights reserved.
#
# This source code is licensed under End User License Agreement found in the
# LICENSE file at http://www.apstra.com/community/eula

import socket
import re
import netmiko
from aeon.exceptions import LoginNotReadyError, ConfigError, CommandError


__all__ = ['Connector']


class Connector(object):
    def __init__(self, hostname, **kwargs):
        self.hostname = hostname
        self.port = kwargs.get('port') or socket.getservbyname('ssh')
        self.user = kwargs.get('user')
        self.passwd = kwargs.get('passwd')

        cros = {
                "device_type" : "cdot_cros",
                "host" : self.hostname,
                "username" : self.user,
                "password" : self.passwd,
                }


        self._nc = netmiko.ConnectHandler(**cros)
        try:
            self._nc = netmiko.ConnectHandler(**cros)

        except Exception as exc:
            raise LoginNotReadyError(exc=exc, message=exc.message)

    def close(self):
        self._nc.disconnect()

    def _sanitize_output(self, output, command):

        #
        # Replace header of the form
        # Running CLI command
        # <cmd>
        #
        output = output.replace("Running CLI command\n%s" % (command), "")

        # Remove color codes etc
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        output = ansi_escape.sub('', output)

        return output

    def execute(self, commands, stop_on_error=True):
        results = []
        exit_code_collector = 0

        for cmd in commands:
            output = ""
            exit_code = 0
            try:
                output = self._nc.send_command(cmd)
            except:
                exit_code = 1

            output = self._sanitize_output(output, cmd)
            exit_code_collector |= exit_code

            results.append(dict(cmd=cmd, exit_code=exit_code,
                                stdout=output,
                                stderr=output))

            if stop_on_error is True and exit_code != 0:
                return False, results

        return bool(0 == exit_code_collector), results

    def configure(self, commands, comment=""):
        cmd_enter_output = ""
        cmd_exec_output = ""
        exit_code = 0
        error_msg = ""
        output=""

        try:
            cmd_enter_output = self._nc.send_config_set(commands)
            cmd_exec_output = self._nc.commit(comment=comment)
            output = cmd_exec_output

        except Exception as e:
            exit_code = 1
            error_msg = e.msg
            output = cmd_enter_output + "\n" + cmd_exec_output

        results = dict(exit_code = exit_code,
                       stdout=output,
                       stderr=error_msg)

        return exit_code, results
