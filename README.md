I no longer use this and last used it on a version of PfSense from ~2022. 

---

Modem/internet-providing-device checker and rebooter. Runs on pfsense and uses an arduino to manage the modem. 

This is intended to work with a device that does not have a [programatically usable] management interface. It uses a photoresistor/color sensor to determine the device status. 



OS requirements:
1) Adjust the interpreter line at the top will vary based on version of pfsense as older versions (< 2.4.5?) do not
    have py3. More modern versions seem to change python version more frequently
   
2) Install uarduno package for the serial driver. This is only needed for some microcontrollers.
    Note uarduino is not in the pfsense pkgs, so it must be obtained from the fbsd package repo.
    The following command is an example for pfsense based on freebsd 11.3:
    `pkg add http://pkg.freebsd.org/FreeBSD:11:amd64/release_3/All/uarduno-1.02_1.txz`
    
3) Add `uarduno_load="YES"` to /boot/loader.conf so the driver is loaded on boot

4) run `kldload uarduno.ko` to manually load without a reboot

5) run with modem_checker_wrapper.sh (usually under cron)