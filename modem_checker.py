#!/usr/bin/env python3

# https://gist.github.com/jjfalling/6feddcafc7d88911db5a4b1b8c6144dc
# Internet health check for pfsense. 
# This communicates with an arduiono to restart a modem or other device when health checks fail. 
# Python3 is required. See older versions for python2 support.  

import argparse
import datetime
import logging
import os
import re
import subprocess
import sys
import time
import traceback
from logging.handlers import TimedRotatingFileHandler

# pyserial
import serial
import termios
from packaging import version

# what bsd device is the arduino?
serDev = '/dev/cuaU0'
#serDev = "/dev/ttyACM0"

# some micro controllers reset on serial connect and need a delay before the controller boots and will respond.
# set to 0 to have no delay, otherwise the number of seconds to wait
serConnectDelay = 3

# number of seconds to timeout when waiting for serial response. This must be higher than
#  RebootDelay in Device Indicator Checker firmware
serialTimeout = 60

# external hosts to test against
hosts_to_ping = ['google.com', '4.2.2.2', '1.1.1.1']

# ip of internal gateway. Set to None if this is running on your gateway.
internal_gw = None

# external interface to bounce. Set to None to disable
ext_interface = 'lagg0.2'

# how long to wait for the modem to finish restarting in minutes
modem_restart_timeout = 10

# how long to wait after the modem restart to start checking it in seconds (to avoid false positives with indicators)
modem_post_restart_check_delay = 60

# send email alert after restarting modem?
send_email = True

logPath = "/var/log"
logName = "modem_checker"
#######################################################################
# TODO:
# - is there a possibility where this can miss the response from writing a command? ie write, go to read but response
#   happens or starts before read? seems ok at 9600, but higher bauds have issues
# - add email for when there is a fatal error (serial port, can't setup, can't communicate with arduino, etc)
#
# - generate error when driver steps not followed? or add automatic setup if ran as root? this needs fbsd 
#   version parsing to get right package (assume only support curent and last versions?). add optional flag 
#   to enable auto setup (should help on upgrades)
# - may also need wrapper script (replace epl?) to handle intepreter issues
# - add rate limiting for emails? per error or per all errors?
# - make mail command and subject configurable? if can do safely
# - add tests including mock serial responses
# - is interface bouncing still needed? maybe check connection before bouncing to avoid it when possible
# - insert git link to version that supported py2
# - fix all var names, doc string, finalize naming (esp of the arduuino code)
# - read settings from arduino to auto set some settings?
# - config file and flags for settings?
# - consider rts/cts/etc?
# - put in a repo?

# terms:
#  microcontroller - device doing sensing and reboots
#  modem - the device used for internet access that will be rebooted


# Design Notes:
# The aruino code should have backwards compat changes unless there are major/minor version changes.
# The python code flags should not have breaking changes unless there are major/minor version changes. 
# python code should not use external libs if not needed

PROGNAME = 'Modem Checker'
VERSION = '1.0.2'

# min version supported
MIN_ARDUINO_FW_VERSION = '1.0.2'

# this is a end of transmission signal which the pylib uses to know when to stop reading from the port
SERIAL_TERMINATOR = b'\x04'
SERIAL_STRIP_STRING = '\r\n\x04'

logFormatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger()
logging.getLogger().setLevel(logging.INFO)

fileHandler = TimedRotatingFileHandler("{0}/{1}.log".format(logPath, logName), when='midnight', interval=1,
                                       backupCount=10)
fileHandler.setFormatter(logFormatter)
#logger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)


def _convert_serial_data_to_string(data):
    """
    Convert the bytes object to string.
    :param data: bytes object
    :return: string
    """
    data = data.decode()
    return data.strip(SERIAL_STRIP_STRING)


def check_min_version(reported_fw_ver):
    """
    Check firmware min version requirement
    :param reported_fw_ver: Firmware version on arduino
    :type reported_fw_ver: string
    :return: True if requirement is met, otherwise false
    :rtype: bool
    """
    if not reported_fw_ver or version.parse(reported_fw_ver) < version.parse(MIN_ARDUINO_FW_VERSION):
        return False
    else:
        return True


def get_status(serial_con):
    """
    Get indicator status
    :param serial_con: serial connection
    :return: string
    """
    serial_con.write(b'status')
    status = serial_con.read_until(expected=SERIAL_TERMINATOR)
    return _convert_serial_data_to_string(status)


def get_settings(serial_con):
    """
    Get settings
    :param serial_con: serial connection
    :return: string
    """
    serial_con.write(b'settings')
    status = serial_con.read_until(expected=SERIAL_TERMINATOR)
    return _convert_serial_data_to_string(status)


def get_fw_version(serial_con):
    """
    Get get arduino firmware version
    :param serial_con: serial connection
    :return: string
    """
    serial_con.write(b'version')
    status = serial_con.read_until(expected=SERIAL_TERMINATOR)
    ver_str = _convert_serial_data_to_string(status)
    # strip everything but the version
    ver_str = re.search('\d+\.\d+\.\d+', ver_str)
    if not ver_str:
        logger.warning('No valid firmware version was reported')
        return None
    else:
        return ver_str[0]


def reboot_device(serial_con):
    """
    Send reboot command
    :param serial_con: serial connection
    :return: bool
    """
    serial_con.write(b'reboot')
    status = serial_con.read_until(expected=SERIAL_TERMINATOR)
    status = _convert_serial_data_to_string(status)
    if "Reboot Completed" not in status:
        logger.error('Modem did not restart correctly. Response: ' + status)
        return False

    return True


def wait_for_modem(serial_con):
    """
    Wait for modem to be in a started state.
    :param serial_con: serial connection
    :param timeout: number of minutes before timing out waiting for modem
    :return: bool
    """
    timeout_time = datetime.datetime.now() + datetime.timedelta(minutes=modem_restart_timeout)

    while datetime.datetime.now() < timeout_time:
        status = get_status(serial_con)
        logger.debug('Modem indicator status is: ' + status)
        if "Indicator On" in status:
            return True
        else:
            time.sleep(10)

    return False


def is_host_pingable(host):
    """
    Check if host is pingable
    :param host: hostname or ip
    :return: bool
    """
    resp = os.system("ping -c 3 " + host + "> /dev/null 2>&1")
    if resp == 0:
        return True
    else:
        return False


def run_internet_check():
    """
    Run ping checks against all external hosts
    :return: bool
    """
    test_passed = False
    for host in hosts_to_ping:
        status = is_host_pingable(host)
        logger.info('Host {h} is pingable: {a}'.format(h=host, a=status))
        if status:
            test_passed = True
            break

    return test_passed


def bounce_interface():
    """
    Bounce external interface.
    :return: None
    """
    os.setpgrp()
    res = subprocess.check_output(["/sbin/ifconfig", ext_interface, "down", ], stderr=subprocess.STDOUT)
    if res:
        logger.info('Output from setting interface to down: {o}'.format(o=res))

    time.sleep(10)
    res = subprocess.check_output(["/sbin/ifconfig", ext_interface, "up"], stderr=subprocess.STDOUT)
    if res:
        logger.info('Output from setting interface to up: {o}'.format(o=res))

    time.sleep(10)
    res = subprocess.check_output(["/etc/rc.linkup", "interface=" + ext_interface, "action=start"],
                                  stderr=subprocess.STDOUT)
    if res:
        logger.info('Output from running rc.linkup: {o}'.format(o=res))

    time.sleep(2)

    return


def close_serial(serial_con):
    """
    Close serial connection

    :param serial_con: serial connection
    :return: None
    """
    try:
        if serial_con.is_open:
            serial_con.close()
            logger.debug("Closed serial port")
        else:
            logger.debug("Serial port is already closed")

    except AttributeError:
        logger.debug("Could not close serial as connection is invalid")
        pass
    return


def send_email_alert():
    """
    Send email alert using pfsense notifications
    :return: None
    """
    msg = 'Modem was restarted due to internet failure at ' + datetime.datetime.now().replace(microsecond=0).isoformat()
    os.system('echo ' + msg + ' |/usr/local/bin/mail.php -s"`hostname` - Notification"')
    return


def main(serial_con):
    parser = argparse.ArgumentParser(description=PROGNAME +
                                                 '\n\nUtility that that checks internet status and restarts a device ' +
                                                 'such as a modem when needed.',
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-d', '--debug', action='store_true', help='enable debug logging')
    parser.add_argument('-s', '--settings', action='store_true', help='Show controller settings')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # ensure firmware supports required features
    mc_fw_version = get_fw_version(serial_con)
    if check_min_version(mc_fw_version):
        logger.debug('Require fw version {min} and found {rep}, checks passed'.format(min=MIN_ARDUINO_FW_VERSION,
                                                                                      rep=mc_fw_version))
    else:
        logger.fatal('Require fw version {min} but found {rep}. Please update the modem checker firmware on the '
                     'microcontroller.'.format(min=MIN_ARDUINO_FW_VERSION, rep=mc_fw_version))
        return

    if args.settings:
        print(get_settings(serial_con))
        return

    logger.info('Starting internet checks')

    logger.info('Checking readability of external hosts')
    internet_status_ok = run_internet_check()
    if internet_status_ok:
        logger.info('At least one external host is reachable. Considering internet up. Exiting.')
        return

    else:
        logger.info('All external host are unreachable. Considering internet down.')

    if internal_gw:
        logger.info('Checking readability of internal gateway')
        if not is_host_pingable(internal_gw):
            logger.info('Internal gateway is down. Not attempting to restart modem. Exiting.')
            return
        else:
            logger.info('Internal gateway is reachable.')

    else:
        logger.info('Internal gateway was not provided, skipping check.')

    # internet seems down an either internal gateway check passed or was skipped.
    logger.warning('Restarting modem as internet is unreachable')
    reboot_device(serial_con)

    logger.info('Waiting {n} seconds before running modem checks'.format(n=modem_post_restart_check_delay))
    time.sleep(modem_post_restart_check_delay)

    logger.info('Modem restart done. Waiting for modem to connect')
    modem_status = wait_for_modem(serial_con)

    if modem_status:
        logger.info('Modem appears to have come back up')
    else:
        logger.error('Timeout hit while waiting for modem to come up')

    # bounce interface even if the modem didn't come up
    if ext_interface:
        logger.info('Bouncing interface')
        bounce_interface()
    else:
        logger.info('Not bouncing interface as no interface was specified')

    logger.info('Done preforming resetting')

    # send email alert if requested
    if send_email:
        send_email_alert()

    return


if __name__ == "__main__":

    serial_con = None
    try:
        serial_con = serial.Serial(serDev, 9600, timeout=serialTimeout)
        logger.debug('Opened serial port {p}'.format(p=serDev))
    except termios.error as err:
        logger.fatal('Cannot open serial port {p}: {e}. Does this device exist and is the baud correct?'.format(
            p=serDev, e=err))
        close_serial(serial_con)
        sys.exit(1)
    except serial.serialutil.SerialException as err:
        logger.fatal('Cannot open serial port {p}: {e}'.format(p=serDev, e=err))
        close_serial(serial_con)
        sys.exit(1)

    if serConnectDelay and serConnectDelay > 0:
        logger.debug('Waiting {} sec for arduino to finish booting before issuing commands'.format(serConnectDelay))
        time.sleep(serConnectDelay)

    try:
        main(serial_con)
    except Exception:
        logger.fatal('Unhandled exception in main function: \n{e}'.format(e=str(traceback.format_exc())))

    close_serial(serial_con)
    sys.exit(0)
