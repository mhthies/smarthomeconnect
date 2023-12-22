#!/usr/bin/env python3
"""
A Nagios compatible check script to monitor the status of an SHC application server or a single interface.

Usage
-----

Use check_shc.py --help for full usage information.

Here are some examples:

Simply monitoring the SHC server status:

    check_shc.py -u http://shc-host:80/base_path

Only monitoring metrics (ignoring the overall server state):

    check_shc.py -u http://shc-host:80/base_path -s -m interface_name.metric_name<50<100

"""
import argparse
import enum
import json
import sys
import urllib.request
import urllib.error
from typing import NoReturn


def main() -> None:
    args = get_arg_parser().parse_args()

    # Do request
    request = urllib.request.Request(f"{args.url[0]}/monitoring", None, {'Accept': "application/json"})
    try:
        response = urllib.request.urlopen(request, timeout=5.0)
        status = response.status
        payload = response.read()
        headers = response.headers
    except urllib.error.HTTPError as e:
        response = e
        status = response.code
        payload = response.read()
        headers = response.headers
    except urllib.error.URLError as e:
        exit_with_report(ServiceStatus.UNKNOWN, f"Failed to connect to SHC web server: {e}")

    if status not in (200, 213, 513):
        exit_with_report(ServiceStatus.UNKNOWN, f"Unexpected HTTP status code from SHC web server: {status}")

    # Parse response
    try:
        data = json.loads(payload.decode(headers.get_content_charset()))
    except Exception as e:
        exit_with_report(ServiceStatus.UNKNOWN, f"HTTP Response from SHC web server was no correctly encoded JSON: {e}")

    if 'interfaces' not in data or 'status' not in data:
        invalid_result()

    # If requested to check a single interface:
    if args.interface is not None:
        interface_name = args.interface[0]
        if interface_name not in data["interfaces"]:
            exit_with_report(ServiceStatus.UNKNOWN,
                             f"Interface '{interface_name} is not present in monitoring data returned from SHC server")

        interface_data = data['interfaces'][interface_name]
        status = interface_data['status']
        exit_with_report(ServiceStatus(status),
                         f"Interface status: {ServiceStatus(interface_data['status']).to_string()}; "
                         + interface_data['message'],
                         "")
    else:
        status = data['status']
        exit_with_report(ServiceStatus(status),
                         f"Overall SHC server status: {ServiceStatus(data['status']).to_string()}",
                         "",)


def invalid_result() -> NoReturn:
    exit_with_report(ServiceStatus.UNKNOWN, "JSON response from SHC web server is not structured as expected.")


def exit_with_report(status: "ServiceStatus", message: str = "", long_message: str = "") -> NoReturn:
    print(f"{status.to_string()}: {message}|\n{long_message}")
    sys.exit(status.exit_code())


def get_arg_parser() -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(description="""
    Nagios-compatible monitoring plugin for monitoring an SHC server via the monitoring endpoint of the web interface

    By default, the script checks the HTTP reachability of the server and the overall status reported by the server
    (see SHC documentation about "Monitoring via HTTP" for more details). If the server is not reachable, the status
    is reported as UNKNOWN (exit code 3). Otherwise, the status from the server is reported as is.

    If the --interface option is given, the status of the specific SHC interface is reported instead, or UNKNOWN if the
    server is not reachable or the interface does not exist.
    """)
    arg_parser.add_argument("-u", "--url", nargs=1, required=True, help="Base URL of the SHC web server")
    arg_parser.add_argument("-i", "--interface", nargs=1,
                            help="The display_name of a specific SHC interface in the monitoring data of the SHC "
                                 "server. If given, the status of this interface is evaluated, instead of the overall "
                                 "server state.")
    return arg_parser


class ServiceStatus(enum.IntEnum):
    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3

    def to_string(self) -> str:
        return self.name

    def exit_code(self) -> int:
        return self.value


if __name__ == "__main__":
    main()
