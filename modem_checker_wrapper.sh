#!/bin/sh
# modem checker wrapper script.

# this installs all of the python deps and will not install them again unless
#  uname -v changes (uses a state file under /tmp). this should handle pfsense
#  upgrades gracefully.

python_interp=`find /usr/local/bin  -type f -name "python3.*" ! -name "*-config"`
release_version=`uname -v | sed -r "s/ //g"`

# check if /tmp/modem_checker_wrapper_$release_version exists, if so skip prep work.
if [ ! -f "/tmp/modem_checker_wrapper_$release_version" ] ; then
  echo "State file does not exist. Ensuring python deps are installed."

  # file does not exist, ensure pip is installed then install python deps
  $python_interp -m ensurepip
  pip=`find /usr/local/bin  -type f -name "pip3.*"`

  $pip install -r /root/modem_checker_requirements.txt

  touch /tmp/modem_checker_wrapper_$release_version

fi

$python_interp /root/modem_checker.py
