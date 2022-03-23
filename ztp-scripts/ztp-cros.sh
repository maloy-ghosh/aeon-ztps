#!/bin/bash
# Copyright 2022-present, Centre For Development of Telematics. All rights reserved.
#

# Variables exposed to this script
# - BOOTFILE_NAME_OPTION: URL from DHCP option 67 (bootfile-name)

# trap and print what failed
function error () {
    echo -e "ERROR: Script failed at $BASH_COMMAND at line $BASH_LINENO." >&2
    exit 1
}
trap error ERR


bootfile_url=$(echo "$BOOTFILE_NAME_OPTION" | awk -F "/" '{print $3}')
if [ -n "$bootfile_url" ]; then
    HTTP="http://${bootfile_url}"
else
    echo "Missing bootfile-name option" >&2
    exit 1
fi

echo ""
echo "-------------------------------------"
echo "ZTP auto-provision from: ${HTTP}"
echo "-------------------------------------"
echo ""

function kickstart_aeon_ztp(){
   wget -O /dev/null ${HTTP}/api/register/cros
}

kickstart_aeon_ztp

# CROS-AUTOPROVISIONING

## exit cleanly, no reboot
exit 0
