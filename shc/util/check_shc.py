#!/usr/bin/env python3
"""
A Nagios compatible check script to monitor the status of an SHC application server or a single interface.

TODO usage
"""
import argparse
import enum
import urllib.request
import urllib.error
from typing import NamedTuple, Optional, Dict, Tuple


def main() -> None:
    args = get_arg_parser().parse_args()

    # Do request
    request = urllib.request.Request(f"{args.url}/monitoring", None, {'Accept': "application/json"})
    try:
        response = urllib.request.urlopen(request, timeout=5.0)  # TODO SSL context
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

    # TODO check HTTP status_code not in (200, 212, 513)
        # Report UNKNOWN with HTTP error (and message?)
    # TODO if interface:
        # TODO if interface does not exist: Report UNKNOWN
        # TODO do metrics checks
        # TODO if not ignore_status:
            # TODO result = max(metrics, interface status)
        # TODO report result, interface message, interface metrics (with thresholds, if given)
    # else
        # TODO do metrics checks
        # TODO if not ignore_status:
            # TODO result = max(metrics, interface status)
        # TODO report result, explicitly defined metrics (with thresholds, if given)


def exit_with_report(status: "ServiceStatus", message: str = "", long_message: str = "",
                     metrics: Dict[str, Tuple[float, Optional[float], Optional[float]]] = {}) -> None:
    # TODO
    pass


def get_arg_parser() -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("-u", "--url", nargs=1, required=True)
    arg_parser.add_argument("-i", "--interface", nargs=1)
    arg_parser.add_argument("-m", "--metric", action='append', nargs=1, type=parse_metrics_arg)
    arg_parser.add_argument("-s", "--ignore-status", action='store_true')
    return arg_parser


class ServiceStatus(enum.Enum):
    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3

    def to_string(self) -> str:
        return self.name

    def exit_code(self) -> int:
        return self.value


class MetricsCheck(NamedTuple):
    interface_name: str
    metric_name: str
    warning_threshold: Optional[float]
    critical_threshold: Optional[float]


ESCAPED_DOT = '\uE042'
ESCAPED_LT = '\uE043'
TRANSLATE_BACK = str.maketrans({ESCAPED_DOT: '.', ESCAPED_LT: '<'})


def parse_metrics_arg(arg: str) -> MetricsCheck:
    """
    Parse a command line argument of the form "interface.metric<5.0<<10" into a `MetricsCheck` object
    """
    # Save escaped '.' and '<', using unicode private use characters
    arg = arg.replace('\\.', ESCAPED_DOT).replace('\\<', ESCAPED_LT)

    # Parse thresholds
    segments = arg.split('<')
    fullname = segments[0]
    next_is_critical_thresh = False
    warning_thresh = None
    critical_thresh = None
    for segment in segments[1:]:
        if not segment:  # Two directly consecutive '<'
            next_is_critical_thresh = True
            continue
        value = float(segment)
        if next_is_critical_thresh:
            critical_thresh = value
        else:
            warning_thresh = value
        next_is_critical_thresh = False

    # Split interface and metric name
    name_parts = fullname.split(".", 1)
    if len(name_parts) != 2:
        raise ValueError("Metric name must consist of interface name and metric name, separated by a single dot.")

    # Construct result
    return MetricsCheck(name_parts[0].translate(TRANSLATE_BACK),
                        name_parts[1].translate(TRANSLATE_BACK),
                        warning_thresh,
                        critical_thresh)


if __name__ == "__main__":
    main()
