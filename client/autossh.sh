#!/bin/sh

### BEGIN INIT INFO
# Provides:          autossh
# Required-Start:    $local_fs $remote_fs $network $syslog
# Required-Stop:     $local_fs $remote_fs $network $syslog
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: starts the autossh
# Description:       starts the autossh
### END INIT INFO

case "$1" in
    start)
	echo "start autossh"
	export AUTOSSH_LOGFILE="/home/pi/autossh.log"
	autossh -M 0 -o "PubkeyAuthentication=yes" -o "StrictHostKeyChecking=false" -o "PasswordAuthentication=no" -o "ServerAliveInterval 60" -o "ServerAliveCountMax 3" -R 7004:localhost:22 tun-user@trololo.info -i /home/pi/.ssh/id_rsa -N -f
	;;
    stop)
	sudo pkill -3 autossh
	;;
    restart)
	sudo pkill -3 autossh
	export AUTOSSH_LOGFILE="/home/pi/autossh.log"
	autossh -M 0 -o "PubkeyAuthentication=yes" -o "StrictHostKeyChecking=false" -o "PasswordAuthentication=no" -o "ServerAliveInterval 60" -o "ServerAliveCountMax 3" -R 7004:localhost:22 tun-user@trololo.info -i /home/pi/.ssh/id_rsa -N -f
	;;
    *)
	echo "Usage: $0 (start|stop)"
	;;
esac
exit 0
