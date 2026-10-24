#!/bin/bash
# For each single-op graph: launch cerebrate-graph on webgpu, run once with a short timeout, report.
D="adb -s 192.168.68.60:5555"; P=18769
for name in "$@"; do
  $D shell "pkill -f 'cerebrate-graph .* $P'" 2>/dev/null
  ( $D shell "cd /data/local/tmp && LD_LIBRARY_PATH=/data/local/tmp nohup setsid ./cerebrate-graph /data/local/tmp/op-$name.onnx webgpu $P > /data/local/tmp/op-test.log 2>&1 < /dev/null &" & sleep 3; kill $! 2>/dev/null ) >/dev/null 2>&1
  for i in $(seq 1 20); do $D shell "grep -q -E 'READY|FATAL' /data/local/tmp/op-test.log" && break; sleep 1; done
  R=$(ssh -o ConnectTimeout=8 -p 2206 droid@127.0.0.1 "cd /home/droid/cg-test && GW=\$(ip route show default | awk '{print \$3}'); timeout 40 /home/droid/mlserver17-venv/bin/python cerebrate-graph/graph-client run \$GW $P --inputs op-${name}_in.npz --reference op-${name}_ref.npz --timeout 25 2>&1 | grep -E 'y: |inference_us|Error' | tr '\n' ' '" 2>/dev/null)
  printf "%-15s %s\n" "$name" "$(echo "$R" | sed -E 's/.*(inference_us=[0-9]+).*(max_abs_diff=[^ ]+).*(cosine=[^ ]+).*/OK \1 \2 \3/' | cut -c1-200)"
  $D shell "pkill -f 'cerebrate-graph .* $P'" 2>/dev/null
done
