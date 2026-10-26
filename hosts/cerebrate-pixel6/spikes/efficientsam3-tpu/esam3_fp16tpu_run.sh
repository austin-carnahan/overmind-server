#!/bin/bash
# Guarded fp16-relaxed Edge TPU run of one EfficientSAM3 vision fragment (runs on
# overmind-01): isolated bench process under a hard timeout, MemAvailable
# sampled every second with a kill below MEM_FLOOR_KB, one attempt only.
# Reports baseline/min free memory, delegate placement, the TPU driver's
# verdict and compile status, load (= compile) and median latency.
# (yoloe-tpu/fp16tpu_run.sh with this spike's paths.)
# DEVENV is prepended to the bench command on the device (e.g. the NNAPI
# cache variables); TAG suffixes the output directory (out-<mode><tag>).
# usage: esam3_fp16tpu_run.sh <fragment> <cpu|tpu16> [timeout_s]
F=$1; MODE=$2; T=${3:-240}; D="adb -s 192.168.68.60:5555"; DIR=/data/local/tmp/esam3-tpu/fp16tpu/$F
MEM_FLOOR_KB=${MEM_FLOOR_KB:-1500000}
base=$($D shell "grep MemAvailable /proc/meminfo" | awk '{print $2}')
$D logcat -c; OUT=out-$MODE${TAG:-}
$D shell "rm -rf $DIR/$OUT; mkdir -p $DIR/$OUT"
( $D shell "cd $DIR && ${DEVENV:-} LD_LIBRARY_PATH=/data/local/tmp timeout $T /data/local/tmp/yoloe/tpu/tflite-nnapi-bench ${F}_float32.tflite $MODE ${INPUTS:-inputs.txt} $OUT ${ITERS:-12} > log-$MODE.txt 2>&1; echo exit=\$? >> log-$MODE.txt" ) & BP=$!
minmem=$base; t0=$(date +%s); guard=""
while kill -0 $BP 2>/dev/null; do
  m=$($D shell "grep MemAvailable /proc/meminfo" | awk '{print $2}')
  [ -n "$m" ] && [ "$m" -lt "$minmem" ] && minmem=$m
  if [ -n "$m" ] && [ "$m" -lt "$MEM_FLOOR_KB" ]; then guard="MEMORY GUARD fired at $((m/1024)) MB"; $D shell "pkill -f tflite-nnapi-bench"; fi
  sleep 1
done
el=$(( $(date +%s) - t0 ))
echo "== $F $MODE: wall ${el}s, free memory baseline $((base/1024)) MB, min $((minmem/1024)) MB (drop $(( (base-minmem)/1024 )) MB) ${guard}"
$D shell "grep -E 'Replacing|model=|reload=|FATAL|exit=' $DIR/log-$MODE.txt | cut -c1-200"
$D logcat -d | grep -E "Started Request|Ops supported|Total Number of TPU|cache|Cache|delegated to CPU|RET_CHECK|crash_dump|Failed to create|Completed Request|Deadline|tombstone" | sed "s/^.\{31\}//; s/(vendor[^)]*)//" | sort | uniq -c | cut -c1-200
