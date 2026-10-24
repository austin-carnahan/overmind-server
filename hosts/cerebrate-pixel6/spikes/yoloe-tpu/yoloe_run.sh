#!/bin/bash
# Step 2B device runs: one cerebrate-graph worker (model, backend) launched by
# hand on a spare port with verbose placement, the eight photos sent through
# graph-client from the guest (outputs saved, first photo compared with the
# desktop reference, timing over repeats), then the worker log tail and the
# NNAPI partitioning lines from logcat. Runs on overmind-01.
# usage: yoloe_run.sh <model.onnx on device> <backend> <port> <guest dir> <tag> <ref prefix>
set -u
M=$1; B=$2; P=$3; G=$4; TAG=$5; REF=$6
D="adb -s 192.168.68.60:5555"
LOG=/data/local/tmp/yoloe-$TAG.log
$D shell "pkill -f 'cerebrate-graph .* $P'" 2>/dev/null
$D logcat -c
( $D shell "cd /data/local/tmp && CEREBRATE_GRAPH_VERBOSE=1 LD_LIBRARY_PATH=/data/local/tmp nohup setsid ./cerebrate-graph $M $B $P > $LOG 2>&1 < /dev/null &" & sleep 5; kill $! 2>/dev/null ) >/dev/null 2>&1
for i in $(seq 1 150); do
  if $D shell "grep -q -E 'READY|FATAL' $LOG"; then break; fi
  if ! $D shell "pgrep -f 'cerebrate-graph .* $P'" >/dev/null; then break; fi
  sleep 2
done
echo "== $TAG worker: $($D shell "grep -E 'READY|FATAL|load' $LOG | tail -2 | cut -c1-160")"
if $D shell "grep -q READY $LOG"; then
  ssh -o ConnectTimeout=8 -p 2206 droid@127.0.0.1 "cd $G && mkdir -p out-$TAG && GW=\$(ip route show default | awk '{print \$3}');
    for i in 0 1 2 3 4 5 6 7; do /home/droid/mlserver17-venv/bin/python /home/droid/cg-test/cerebrate-graph/graph-client run \$GW $P --inputs in\$i.npz --save out-$TAG/out\$i.npz > /dev/null || echo FAIL \$i; done;
    /home/droid/mlserver17-venv/bin/python /home/droid/cg-test/cerebrate-graph/graph-client run \$GW $P --inputs in0.npz --reference ${REF}0.npz --repeat 10 | tail -8" 2>&1 | grep -v setlocale
fi
echo "== $TAG placement (worker log):"; $D shell "grep -i -E 'node placement|nodes placed|assigned|Execution Provider|partition' $LOG | sort | uniq -c | sort -rn | head -8 | cut -c1-200"
echo "== $TAG logcat (NNAPI):"; $D logcat -d | grep -i -E 'number of partitions|nodes supported by NNAPI|supported by NNAPI|google-edgetpu|Found interface|compilation finished|Ops supported' | cut -c1-200 | sort | uniq -c | head -10
$D shell "pkill -f 'cerebrate-graph .* $P'" 2>/dev/null
exit 0
