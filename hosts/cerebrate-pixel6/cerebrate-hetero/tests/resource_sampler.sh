#!/bin/bash
# Samples the phone once a second (runs on overmind-01) while a test runs:
# MemAvailable, and the RSS / peak RSS (VmHWM) of the cerebrate-hetero
# listening on <port>. Stops when <stop file> appears; prints the baseline and
# minimum free memory, the worker's steady RSS after load and its peak.
# usage: resource_sampler.sh <port> <stop file>
P=$1; STOP=$2; D="adb -s 192.168.68.60:5555"
base=""; minmem=99999999; maxrss=0; hwm=0; steady=""
while [ ! -f "$STOP" ]; do
  out=$($D shell "grep MemAvailable /proc/meminfo; for pid in \$(pgrep -f '[c]erebrate-hetero $P '); do [ \"\$(cat /proc/\$pid/comm 2>/dev/null)\" = cerebrate-heter ] && grep -E 'VmRSS|VmHWM' /proc/\$pid/status; done")
  m=$(echo "$out" | awk '/MemAvailable/ {print $2}'); r=$(echo "$out" | awk '/VmRSS/ {print $2}'); h=$(echo "$out" | awk '/VmHWM/ {print $2}')
  [ -z "$base" ] && base=$m
  [ -n "$m" ] && [ "$m" -lt "$minmem" ] && minmem=$m
  [ -n "$r" ] && { [ -z "$steady" ] && steady=$r; [ "$r" -gt "$maxrss" ] && maxrss=$r; }
  [ -n "$h" ] && [ "$h" -gt "$hwm" ] && hwm=$h
  sleep 1
done
echo "RESOURCES port=$P free_baseline_mb=$((base/1024)) free_min_mb=$((minmem/1024)) drop_mb=$(((base-minmem)/1024)) rss_first_mb=$((${steady:-0}/1024)) rss_max_mb=$((maxrss/1024)) vmhwm_mb=$((hwm/1024))"
