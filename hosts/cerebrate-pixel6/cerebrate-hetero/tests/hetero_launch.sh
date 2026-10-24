#!/bin/bash
# Hand-launch cerebrate-hetero on the Pixel (runs on overmind-01): waits for
# READY with a memory guard during load, prints the READY line.
# usage: hetero_launch.sh <port> <args after port...>
P=$1; shift; D="adb -s 192.168.68.60:5555"; LOG=/data/local/tmp/hetero/worker-$P.log
$D shell "pkill -f 'cerebrate-hetero $P '" 2>/dev/null
( $D shell "cd /data/local/tmp/hetero && LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp nohup setsid ./cerebrate-hetero $P $* > $LOG 2>&1 < /dev/null &" & sleep 5; kill $! 2>/dev/null ) >/dev/null 2>&1
minmem=99999999
for i in $(seq 1 120); do
  m=$($D shell "grep MemAvailable /proc/meminfo" | awk '{print $2}'); [ -n "$m" ] && [ "$m" -lt "$minmem" ] && minmem=$m
  if [ -n "$m" ] && [ "$m" -lt 1500000 ]; then echo "MEMORY GUARD"; $D shell "pkill -f 'cerebrate-hetero $P '"; break; fi
  if $D shell "grep -q -E 'READY|FATAL' $LOG"; then break; fi
  sleep 1
done
echo "min free memory during load: $((minmem/1024)) MB"; $D shell "grep -E 'READY|FATAL|WARNING|Replacing' $LOG | cut -c1-260"
