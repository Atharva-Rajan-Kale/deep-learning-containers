# Copyright 2019-2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
from __future__ import absolute_import

import os.path
import shlex
import subprocess
import sys
import tensorflow as tf

try:
    subprocess.call(
        ["/bin/bash", "/usr/local/bin/bash_telemetry.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
except:
    pass


if tf.test.is_built_with_cuda():
    # run compat mounting by default
    try:
        subprocess.run(["bash", "-m", "/usr/local/bin/start_cuda_compat.sh"])
    except Exception as e:
        print(f"Error running script: {e}")

subprocess.check_call(shlex.split(" ".join(sys.argv[1:])))
