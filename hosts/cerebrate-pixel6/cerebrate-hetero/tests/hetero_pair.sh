#!/bin/bash
# (re)start the EdgeSAM (8793) and YOLOE (8795) test workers with the given configs (runs on overmind-01)
A="adb -s 192.168.68.60:5555"; W=/data/local/tmp/edgesam/worker
$A shell "pkill -f '[c]erebrate-hetero 879'; sleep 1; rm -f $W/worker-879*.log" < /dev/null
timeout 5 $A shell "cd $W && LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp nohup setsid ./cerebrate-hetero 8793 --config $1 > worker-8793.log 2>&1 < /dev/null &"
timeout 5 $A shell "cd $W && LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp nohup setsid ./cerebrate-hetero 8795 --config $2 > worker-8795.log 2>&1 < /dev/null &"
for i in $(seq 1 40); do n=$($A shell "grep -l -E 'READY|FATAL' $W/worker-879*.log 2>/dev/null | wc -l" < /dev/null); [ "$n" -ge 2 ] && break; sleep 2; done
$A shell "grep -h -E 'READY|FATAL' $W/worker-879*.log | sed 's/ config=.*//'" < /dev/null
