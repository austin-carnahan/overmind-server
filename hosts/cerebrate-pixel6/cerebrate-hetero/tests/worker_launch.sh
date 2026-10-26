#!/bin/bash
# Hand-launch a cerebrate-hetero build on the Pixel (runs on overmind-01) from
# a test directory, on a test port: stops any earlier instance on that port,
# waits for READY (or FATAL) with a memory guard during load, prints the READY
# line and the minimum free memory seen. Generalizes hetero_launch.sh.
# usage: worker_launch.sh <dir> <port> <args after port...>   (or: worker_launch.sh <dir> <port> stop)
DIR=$1; P=$2; shift 2; D="adb -s 192.168.68.60:5555"; LOG=$DIR/worker-$P.log
$D shell "pkill -f '[c]erebrate-hetero $P '" 2>/dev/null
[ "$1" = stop ] && exit 0
( $D shell "cd $DIR && LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp nohup setsid ./cerebrate-hetero $P $* > $LOG 2>&1 < /dev/null &" & sleep 5; kill $! 2>/dev/null ) >/dev/null 2>&1
minmem=99999999
for i in $(seq 1 180); do
  m=$($D shell "grep MemAvailable /proc/meminfo" | awk '{print $2}'); [ -n "$m" ] && [ "$m" -lt "$minmem" ] && minmem=$m
  if [ -n "$m" ] && [ "$m" -lt 1500000 ]; then echo "MEMORY GUARD"; $D shell "pkill -f '[c]erebrate-hetero $P '"; break; fi
  if $D shell "grep -q -E 'READY|FATAL' $LOG"; then break; fi
  sleep 1
done
echo "min free memory during load: $((minmem/1024)) MB"; $D shell "grep -E 'READY|FATAL|WARNING' $LOG | cut -c1-300"
