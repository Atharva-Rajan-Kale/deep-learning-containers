# Copyright 2018-2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import argparse
import json
import logging
import multiprocessing
import os
import re
import signal
import sys

import botocore.session
import requests

TIMEOUT_SECS = 5
REGION_MAPPING = {
    "ap-northeast-1": "ddce303c",
    "ap-northeast-2": "528c8d92",
    "ap-southeast-1": "c35f9f00",
    "ap-southeast-2": "d2add9c0",
    "ap-south-1": "9deb4123",
    "ca-central-1": "b95e2bf4",
    "eu-central-1": "bfec3957",
    "eu-north-1": "b453c092",
    "eu-west-1": "d763c260",
    "eu-west-2": "ea20d193",
    "eu-west-3": "1894043c",
    "sa-east-1": "030b4357",
    "us-east-1": "487d6534",
    "us-east-2": "72252b46",
    "us-west-1": "d02c1125",
    "us-west-2": "d8c0d063",
    "af-south-1": "08ea8dc5",
    "eu-south-1": "29566eac",
    "me-south-1": "7ea07793",
    "ap-southeast-7": "1699f14f",
    "ap-southeast-3": "be0a3174",
    "me-central-1": "6e06aaeb",
    "ap-east-1": "5e1fbf92",
    "ap-south-2": "50209442",
    "ap-northeast-3": "fa298003",
    "ap-southeast-5": "5852cd87",
    "us-northeast-1": "bbf9e961",
    "ap-southeast-4": "dc6f76ce",
    "mx-central-1": "ed0da79c",
    "il-central-1": "2fb2448e",
    "ap-east-2": "8947749e",
    "ca-west-1": "ea83ea06",
    "eu-south-2": "df2c9d70",
    "eu-central-2": "aa7aabcc",
}


def requests_helper(url, headers=None, timeout=0.1):
    """
    Requests to get instance metadata using imdsv1 and imdsv2
    :param url: str, url to get the request
    :param headers: str, headers needed to make a request
    :param timeout: float, timeout value for a request
    """
    response = None
    try:
        if headers:
            response = requests.get(url, headers=headers, timeout=timeout)
        else:
            response = requests.get(url, timeout=timeout)

    except requests.exceptions.RequestException as e:
        logging.error("Request exception: {}".format(e))

    return response


def requests_helper_imds(url, token=None):
    """
    Requests to get instance metadata using imdsv1 and imdsv2
    :param url: str, url to get the request
    :param token: str, token is needed to use imdsv2
    """
    response_text = None
    response = None
    headers = None
    if token:
        headers = {"X-aws-ec2-metadata-token": token}
    timeout = 1
    try:
        while timeout <= 3:
            if headers:
                response = requests.get(url, headers=headers, timeout=timeout)
            else:
                response = requests.get(url, timeout=timeout)
            if response:
                break
            timeout += 1

    except requests.exceptions.RequestException as e:
        logging.error("Request exception: {}".format(e))

    if response is not None and not (400 <= response.status_code < 600):
        response_text = response.text

    return response_text


def get_imdsv2_token():
    """
    Retrieve token using imdsv2 service
    """
    response = None
    token = None
    headers = {"X-aws-ec2-metadata-token-ttl-seconds": "600"}
    url = "http://169.254.169.254/latest/api/token"
    timeout = 1

    try:
        while timeout <= 3:
            response = requests.put(url, headers=headers, timeout=timeout)
            if response:
                break
            timeout += 1
    except requests.exceptions.RequestException as e:
        logging.error("Request exception: {}".format(e))

    if response is not None and not (400 <= response.status_code < 600):
        token = response.text

    return token


def _validate_instance_id(instance_id):
    """
    Validate instance ID
    """
    instance_id_regex = r"^(i-\S{17})"
    compiled_regex = re.compile(instance_id_regex)
    match = compiled_regex.match(instance_id)

    if not match:
        return None

    return match.group(1)


def _retrieve_instance_id(token=None):
    """
    Retrieve instance ID from instance metadata service
    """
    instance_id = None
    instance_url = "http://169.254.169.254/latest/meta-data/instance-id"

    if token:
        instance_id = requests_helper_imds(instance_url, token)
    else:
        instance_id = requests_helper_imds(instance_url)

    if instance_id:
        instance_id = _validate_instance_id(instance_id)

    return instance_id


def _retrieve_instance_region(token=None):
    """
    Retrieve instance region from instance metadata service
    """
    region = None
    response_json = None

    region_url = "http://169.254.169.254/latest/dynamic/instance-identity/document"

    if token:
        response_text = requests_helper_imds(region_url, token)
    else:
        response_text = requests_helper_imds(region_url)

    if response_text:
        response_json = json.loads(response_text)

        if response_json["region"] in REGION_MAPPING:
            region = response_json["region"]

    return region


def _retrieve_device():
    return (
        "gpu"
        if os.path.isdir("/usr/local/cuda")
        else (
            "eia"
            if os.path.isdir("/opt/ei_tools")
            else (
                "neuron"
                if os.path.exists("/usr/local/bin/tensorflow_model_server_neuron")
                else "cpu"
            )
        )
    )


def _retrieve_cuda():
    cuda_version = ""
    try:
        cuda_path = os.path.basename(os.readlink("/usr/local/cuda"))
        cuda_version_search = re.search(r"\d+\.\d+", cuda_path)
        cuda_version = "" if not cuda_version_search else cuda_version_search.group()
    except Exception as e:
        logging.error(f"Failed to get cuda path: {e}")
    return cuda_version


def _retrieve_os():
    version = ""
    name = ""
    with open("/etc/os-release", "r") as f:
        for line in f.readlines():
            if re.match(r"^ID=\w+$", line):
                name = re.search(r"^ID=(\w+)$", line).group(1)
            if re.match(r'^VERSION_ID="\d+\.\d+"$', line):
                version = re.search(r'^VERSION_ID="(\d+\.\d+)"$', line).group(1)
    return name + version


def parse_args():
    """
    Parsing function to parse input arguments.
    Return: args, which containers parsed input arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--framework",
        choices=["tensorflow", "mxnet", "pytorch", "base", "vllm"],
        help="framework of container image.",
        required=True,
    )
    parser.add_argument(
        "--framework-version", help="framework version of container image.", required=True
    )
    parser.add_argument(
        "--container-type",
        choices=["training", "inference", "general"],
        help="What kind of jobs you want to run on container. Either training or inference.",
        required=True,
    )

    args, _unknown = parser.parse_known_args()

    fw_version_pattern = r"\d+(\.\d+){1,2}(-rc\d)?"

    # PT 1.10 and above has +cpu or +cu113 string, so handle accordingly
    if args.framework == "pytorch":
        pt_fw_version_pattern = r"(\d+(\.\d+){1,2}(-rc\d)?)((\+cpu)|(\+cu\d{3})|(a0\+git\w{7}))"
        pt_fw_version_match = re.fullmatch(pt_fw_version_pattern, args.framework_version)
        if pt_fw_version_match:
            args.framework_version = pt_fw_version_match.group(1)
    assert re.fullmatch(fw_version_pattern, args.framework_version), (
        f"args.framework_version = {args.framework_version} does not match {fw_version_pattern}\n"
        f"Please specify framework version as X.Y.Z or X.Y."
    )
    # TFS 2.12.1 still uses TF 2.12.0 and breaks the telemetry check as it is checking TF version
    # instead of TFS version. WE are forcing the version we want.
    if (
        args.framework == "tensorflow"
        and args.container_type == "inference"
        and args.framework_version == "2.12.0"
    ):
        args.framework_version = "2.12.1"

    return args


def query_bucket(instance_id, region):
    """
    GET request on an empty object from an Amazon S3 bucket
    """

    response = None
    args = parse_args()
    framework, framework_version, container_type = (
        args.framework,
        args.framework_version,
        args.container_type,
    )

    py_version = sys.version.split(" ")[0]

    if instance_id is not None and region is not None:
        url = (
            "https://aws-deep-learning-containers-{0}.s3.{1}.amazonaws.com"
            "/dlc-containers-{2}.txt?x-instance-id={2}&x-framework={3}&x-framework_version={4}&x-py_version={5}&x-container_type={6}".format(
                REGION_MAPPING[region],
                region,
                instance_id,
                framework,
                framework_version,
                py_version,
                container_type,
            )
        )
        response = requests_helper(url, timeout=0.2)
        if os.environ.get("TEST_MODE") == str(1):
            with open(os.path.join(os.sep, "tmp", "test_request.txt"), "w+") as rf:
                rf.write(url)

    logging.debug("Query bucket finished: {}".format(response))

    return response


def tag_instance(instance_id, region):
    """
    Apply instance tag on the instance that is running the container using botocore
    """
    args = parse_args()
    framework, framework_version, container_type = (
        args.framework,
        args.framework_version,
        args.container_type,
    )
    py_version = sys.version.split(" ")[0]
    device = _retrieve_device()
    cuda_version = f"_cuda{_retrieve_cuda()}" if device == "gpu" else ""
    os_version = _retrieve_os()

    tag = f"{framework}_{container_type}_{framework_version}_python{py_version}_{device}{cuda_version}_{os_version}"
    tag_struct = {"Key": "aws-dlc-autogenerated-tag-do-not-delete", "Value": tag}

    request_status = None
    if instance_id and region:
        try:
            session = botocore.session.get_session()
            ec2_client = session.create_client("ec2", region_name=region)
            response = ec2_client.create_tags(Resources=[instance_id], Tags=[tag_struct])
            request_status = response.get("ResponseMetadata").get("HTTPStatusCode")
            if os.environ.get("TEST_MODE") == str(1):
                with open(os.path.join(os.sep, "tmp", "test_tag_request.txt"), "w+") as rf:
                    rf.write(json.dumps(tag_struct, indent=4))
        except Exception as e:
            logging.error(f"Error. {e}")
        logging.debug("Instance tagged successfully: {}".format(request_status))
    else:
        logging.error("Failed to retrieve instance_id or region")

    return request_status


def main():
    """
    Invoke bucket query
    """
    # Logs are not necessary for normal run. Remove this line while debugging.
    logging.getLogger().disabled = True

    logging.basicConfig(level=logging.ERROR)

    token = None
    instance_id = None
    region = None
    token = get_imdsv2_token()
    if token:
        instance_id = _retrieve_instance_id(token)
        region = _retrieve_instance_region(token)
    else:
        instance_id = _retrieve_instance_id()
        region = _retrieve_instance_region()

    bucket_process = multiprocessing.Process(target=query_bucket, args=(instance_id, region))
    tag_process = multiprocessing.Process(target=tag_instance, args=(instance_id, region))

    bucket_process.start()
    tag_process.start()

    tag_process.join(TIMEOUT_SECS)
    bucket_process.join(TIMEOUT_SECS)

    if tag_process.is_alive():
        os.kill(tag_process.pid, signal.SIGKILL)
        tag_process.join()
    if bucket_process.is_alive():
        os.kill(bucket_process.pid, signal.SIGKILL)
        bucket_process.join()


if __name__ == "__main__":
    main()
