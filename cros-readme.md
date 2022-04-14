## ZTP basic message flow
Following messages are involved.

- Device comes up and sends DHCP resquests in network.

- DHCP server provides `bootfile-name` script url together with ip address information.

- Device downloads the scripts and executes it, which internally triggers ZTP server to initiate bootstrapping.

- ZTP server sends configuration to device and upgrades release if version mismatch is detected.

## DHCP Server configuration

Following section needs to be added in DHCP server configuration (assuming isc-dhcp-server)

```
class "cros" {
     match if (substring(option vendor-class-identifier, 0, 5) = "cros.");
     option bootfile-name "http://<ztpserverip>:8080/downloads/ztp-cros.sh";
}
```

## CROS
Following are important directories for CROS devices (`Browse files`)

- `etc/configs/cros:` Configuration files for CROS devices.

- `etc/profiles/cros:` OS selector configuration for CROS devices.

- `vendor_images/cros:` Release upgrade files for CROS devices.

Details of these are

### etc/configs/cros

When a device initiates bootstrapping, configuration files are prioritized as

- First a file `etc/configs/cros/<SERIALNUM>/startup.cfg` is searched. If this file is found, only this configuration file is played to device.

- If `startup.cfg` file is not found, following configuration are played in this order
  
  - Device independent configuration files are played. 

    - `etc/configs/cros/all.cfg:` Configuration in device cfg file syntax.

    - `etc/configs/cros/all.yaml.j2:` Configuration in YAML format.
  
  - Device model specific configuration files are played. 

    - `etc/configs/cros/<MODEL>.cfg`

    - `etc/configs/cros/<MODEL>.yaml.j2`
  
  - Device specific configuration files are played. 

    - `etc/configs/cros/<SERIALNUM>/device.cfg`

    - `etc/configs/cros/<SERIALNUM>/device.yaml.j2`

### etc/profiles/cros/os-selector.cfg

Syntax of os-selector file is 

```
B6FADFCD381F:
    regex_match: CROS-H-1\.4\.10-4952
    image: onie-rootfs-CROS-1.4.10.bin

spt2-lxc:
    regex_match: CROS-H-.*
    image: 

default:
    regex_match: CROS-.*
    image: 
  
```

ZTP server tries to match (`regex_match`) incoming device version with selector configuration. **If regex does not match and `image` is specified corresponding release is upgraded.**

For matching following preference order is maintained

- Look for exact match for `SERIALNUM`.

- Next look for match for `MODEL`.

- Otherwise `default` target is matched.

