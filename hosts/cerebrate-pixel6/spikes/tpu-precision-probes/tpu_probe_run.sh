#!/bin/bash
# Run one probe model in one mode on the Pixel (cpu | tpu | tpu16) with the
# TFLite NNAPI bench; report delegate placement, Edge TPU driver verdict and
# compile status, latency and the minimum MemAvailable (memory guard kills the
# bench below 800 MB). Runs on overmind-01.  usage: tpu_probe_run.sh <model> <mode>
M=$1; MODE=$2; D="adb -s 192.168.68.60:5555"; DIR=/data/local/tmp/tpuprobe
$D logcat -c; $D shell "rm -rf $DIR/out-$M-$MODE; mkdir -p $DIR/out-$M-$MODE"
( $D shell "cd $DIR && LD_LIBRARY_PATH=/data/local/tmp /data/local/tmp/yoloe/tpu/tflite-nnapi-bench $M.tflite $MODE $M.txt out-$M-$MODE 12 > log-$M-$MODE.txt 2>&1" ) & BP=$!
minmem=99999999
while kill -0 $BP 2>/dev/null; do
  m=$($D shell "grep MemAvailable /proc/meminfo" | awk '{print $2}'); [ -n "$m" ] && [ "$m" -lt "$minmem" ] && minmem=$m
  if [ -n "$m" ] && [ "$m" -lt 800000 ]; then echo "MEMORY GUARD at $m kB"; $D shell "pkill -f tflite-nnapi-bench"; fi; sleep 1
done
rep=$($D shell "grep -o 'Replacing [0-9]* out of [0-9]*' $DIR/log-$M-$MODE.txt | head -1")
res=$($D shell "grep -o -E 'load_us=[0-9]+|median_us=-?[0-9]+|FATAL.*' $DIR/log-$M-$MODE.txt | tr '\n' ' '")
tpu=$($D logcat -d | grep -o -E "Ops supported = [0-9]+, not supported = [0-9]+|Completed Request #[0-9]+, Status: [0-9]+|RET_CHECK failed[^(]*|Failed to create[^.]*|crash_dump" | sed 's/Completed Request #[0-9]*, //' | sort | uniq -c | tr '\n' ';' | tr -s ' ')
printf "%-16s %-6s | %-22s | %s| tpu: %s| minmem %d MB\n" "$M" "$MODE" "${rep:-no delegation}" "$res" "${tpu:-none}" $((minmem/1024))
