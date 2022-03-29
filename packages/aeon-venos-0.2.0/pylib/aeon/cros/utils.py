#!/usr/bin/env python

# Script: utils.py
# Author: Maloy Ghosh <mghosh@cdot.in>
#
# Purpose:

SERVICE_MAP = {
        "sshd" : "sshd",
        "ssh"  : "sshd",

        "telnetd" : "telnetd",
        "telnet"  : "telnetd",

        "snmp"    : "snmp-server",
        "snmpd"    : "snmp-server",
        "snmp-server" : "snmp-server",

        "dns-resolver" : "dns-resolver",
        "dns"          : "dns-resolver",

        "ntpd"         : "ntpd",
        "ntp"          : "ntpd",

        };

WHITELIST_SERVICE_MAP = {
        "ssh" : "SSH",
        "sshd" : "SSH",

        "telnet" : "TELNET",
        "telnetd" : "TELNET",


        "snmp" : "SNMP",
        "snmpd" : "SNMP",
        "snmp-server" : "SNMP",

        "dns" : "DNS",
        "dns-resolver" : "DNS",
        }

REQUIRE_DEAFULT_VRF = ["dns", "node-exporter"]



def if_name_to_path(name):
    if (name.find(".") != -1):
        return "interface subif %s" % (name)


    inttaglist = ["bvi", "bundle", "vxlan", "mgmt", "tun"]
    iftype = "none"
    path = "none"

    tag = "phy"
    if name.find("%s-" % (tag)) != -1:
        iftype = "physical"
        path = name.split("-")[1].replace("_", "/")

    else:
        for tag in inttaglist:
            if name.find("%s-" % tag) != -1:
                iftype = tag;
                path = name.split("-")[1]
                break;

    return "%s %s" % (iftype, path)

def ip_from_ipprefix(ipprefix):
    return ipprefix.split("/")[0]


def prefix_from_ipprefix(ipprefix):
    if (ipprefix.find("/") != -1):
        return ipprefix.split("/")[1]

    elif (ipprefix.find(":") != -1):
        return "128"

    else:
        return "32"

def vrfcmd_from_vrfname(vrf):
    if (vrf == "global" or vrf == "default"):
        return ""
    else:
        return "vrf %s" % (vrf)

def breakout_str(value):
    if (value == 2):
        return "to-two"

    elif (value == 4):
        return "to-four"


def service_cmd(service):
    try:
        return "service %s" % (SERVICE_MAP[service.lower()])
    except KeyError:
        pass

def whitelist_service_cmd(subnet, service):
    op = ""
    try:
        s_lower = service.lower()
        w_lower = WHITELIST_SERVICE_MAP[s_lower].lower()
        op += "management-acl whitelist %s %s" % (subnet, w_lower)
    except KeyError:
        pass

    return op

def jinja2_register_all_funcs(basedict):
    basedict['if_name_to_path'] = if_name_to_path;
    basedict['ip_from_ipprefix'] = ip_from_ipprefix;
    basedict['prefix_from_ipprefix'] = prefix_from_ipprefix;
    basedict['vrfcmd_from_vrfname'] = vrfcmd_from_vrfname;
    basedict['breakout_str'] = breakout_str;
    basedict['service_cmd'] = service_cmd;
    basedict['whitelist_service_cmd'] = whitelist_service_cmd;
