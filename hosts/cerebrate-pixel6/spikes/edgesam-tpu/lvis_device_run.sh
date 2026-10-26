#!/bin/bash
# EdgeSAM fast pipeline (TPU stage -> GPU fp32 neck -> GPU fp32 decoder) on
# one batch of the LVIS selection set (runs on overmind-01; the batch arrives
# as a tar on stdin, from lvis_device_prep.py's output). TPU stage from the
# NNAPI compilation cache; batch inputs are deleted afterwards, outputs kept.
# usage: lvis_device_run.sh <batch>  < batch.tar
B=$1; A="adb -s 192.168.68.60:5555"; DEV=/data/local/tmp/edgesam/lvis/b$B; E=/data/local/tmp/edgesam
T1=$E/fp16tpu/T1/T1_float32.tflite; TOK=edgesam3x-T1-112fe4dfdda0aa03-fp16r-tflite2.16.1
$A shell "rm -rf $DEV; mkdir -p $DEV" < /dev/null
$A exec-in "tar xf - -C $DEV"
$A shell "cd $DEV && n=\$(wc -l < t1_inputs.txt) && m=\$(wc -l < dec_inputs.txt) && mkdir -p t1out n1out decout && \
  NNAPI_CACHE_DIR=$E/nnapi-cache NNAPI_MODEL_TOKEN=$TOK LD_LIBRARY_PATH=/data/local/tmp timeout 600 /data/local/tmp/yoloe/tpu/tflite-nnapi-bench $T1 tpu16 t1_inputs.txt t1out \$n | grep model= ; \
  LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp timeout 600 $E/dec/litert_e2e $E/fp16tpu/N1/N1_float32.tflite gpu req n1_inputs.txt n1out \$((2*n)) 0 fp32 2>&1 | grep -E 'total median|FATAL'; \
  LD_LIBRARY_PATH=/data/local/tmp/litert-2.3.0:/data/local/tmp timeout 600 $E/dec/litert_e2e $E/dec/edgesam3x-box-decoder-fp32.tflite gpu req dec_inputs.txt decout \$((2*m)) 0 fp32 2>&1 | grep -E 'total median|FATAL'; \
  rm -f in*.bin; echo batch $B: \$n photos \$m boxes, \$(ls decout | wc -l) decoder outputs" < /dev/null
