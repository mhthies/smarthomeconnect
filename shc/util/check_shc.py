#!/usr/bin/env python3
"""
A Nagios compatible check script to monitor the status of an SHC application server or a single interface.

TODO usage
"""
import argparse
import enum
import json
import re
import sys
import urllib.request
import urllib.error
from typing import NamedTuple, Optional, Tuple, NoReturn, List


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
        status = ServiceStatus.OK if args.ignore_status else interface_data['status']
        metrics_check: MetricsCheck
        missing_metrics = []
        display_metrics = []
        for metrics_check in args.metric or []:
            if metrics_check.interface_name != interface_name:
                continue
            if metrics_check.metric_name not in interface_data['metrics']:
                status = ServiceStatus.UNKNOWN
                missing_metrics.append(metrics_check.metric_name)
                display_metrics.append((metrics_check, float('NaN')))
                continue
            value = interface_data['metrics'][metrics_check.metric_name]
            status = max(status, metrics_check.check_value(value))
            display_metrics.append((metrics_check, value))
        # Add all other metrics of the interface for displaying
        for metric, value in interface_data['metrics'].items():
            if metric not in {mc.metric_name for mc in args.metric if mc.interface_name == interface_name}:
                display_metrics.append((MetricsCheck(interface_name, metric, None, None, None, None), value))
        exit_with_report(ServiceStatus(status),
                         f"Interface status: {ServiceStatus(interface_data['status']).to_string()}; "
                         + interface_data['message']
                         + (f" [missing metrics: {', '.join(missing_metrics)}]" if missing_metrics else ''),
                         "",
                         display_metrics)
    else:
        status = ServiceStatus.OK if args.ignore_status else data['status']
        metrics_check: MetricsCheck
        missing_metrics = []
        display_metrics = []
        for metrics_check in args.metric or []:
            try:
                value = data['interfaces'][metrics_check.interface_name]['metrics'][metrics_check.metric_name]
                status = max(status, metrics_check.check_value(value))
            except KeyError:
                status = ServiceStatus.UNKNOWN
                missing_metrics.append(metrics_check.metric_name)
                value = float('NaN')
            display_metrics.append((metrics_check, value))
        exit_with_report(ServiceStatus(status),
                         f"Overall SHC server status: {ServiceStatus(data['status']).to_string()}" + (
                             f" [missing metrics: {', '.join(missing_metrics)}]"
                             if missing_metrics else ''),
                         "",
                         display_metrics)


def invalid_result() -> NoReturn:
    exit_with_report(ServiceStatus.UNKNOWN, "JSON response from SHC web server is not structured as expected.")


def exit_with_report(status: "ServiceStatus", message: str = "", long_message: str = "",
                     metrics: List[Tuple["MetricsCheck", float]] = []) -> NoReturn:
    perf_data = " ".join(metric.format_as_perf_data(value) for metric, value in metrics)
    print(f"{status.to_string()}: {message}|{perf_data}\n{long_message}")
    sys.exit(status.exit_code())


def get_arg_parser() -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("-u", "--url", nargs=1, required=True)
    arg_parser.add_argument("-i", "--interface", nargs=1)
    arg_parser.add_argument("-m", "--metric", action='append', nargs=1, type=parse_metrics_arg)
    arg_parser.add_argument("-s", "--ignore-status", action='store_true')
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


class MetricsCheck(NamedTuple):
    interface_name: str
    metric_name: str
    warning_if_lt: Optional[float]
    warning_if_gt: Optional[float]
    critical_if_lt: Optional[float]
    critical_if_gt: Optional[float]

    def check_value(self, value: float) -> ServiceStatus:
        if self.critical_if_lt is not None and value < self.critical_if_lt or \
                self.critical_if_gt is not None and value > self.critical_if_gt:
            return ServiceStatus.CRITICAL
        if self.warning_if_lt is not None and value < self.warning_if_lt or \
                self.warning_if_gt is not None and value > self.warning_if_gt:
            return ServiceStatus.WARNING
        return ServiceStatus.OK

    def format_as_perf_data(self, value: float) -> str:
        return f"'{self.interface_name}.{self.metric_name}'" \
               f"={value};{self._format_range(self.warning_if_lt, self.warning_if_gt)};" \
               f"{self._format_range(self.critical_if_lt, self.critical_if_gt)}"

    @staticmethod
    def _format_range(lt: Optional[float], gt: Optional[float]) -> str:
        if lt is None:
            if gt is None:
                return ""
            else:
                return f"~:{gt}"
        else:
            if gt is None:
                return f"{lt}:"
            elif lt < gt:
                return f"{lt}:{gt}"
            else:
                return f"@{gt}:{lt}"


# These unicode characters are private use and neither listed to be assigned on
# https://www.evertype.com/standards/csur/ , nor on https://mufi.info/m.php?p=mufichars&i=2&v=E6
ESCAPED_DOT = '\uE6D0'
ESCAPED_LT = '\uE6D1'
ESCAPED_GT = '\uE6D2'
TRANSLATE_BACK = str.maketrans({ESCAPED_DOT: '.', ESCAPED_LT: '<', ESCAPED_GT: '>'})


def pairwise(iterable):
    a = iter(iterable)
    return zip(a, a)


def parse_metrics_arg(arg: str) -> MetricsCheck:
    """
    Parse a command line argument of the form "interface.metric<5.0<<10" into a `MetricsCheck` object
    """
    # Save escaped '.' and '<', using unicode private use characters
    arg = arg.replace('\\.', ESCAPED_DOT).replace('\\<', ESCAPED_LT).replace('\\>', ESCAPED_GT)

    # Parse thresholds
    # TODO parse Nagios Range format? https://nagios-plugins.org/doc/guidelines.html#THRESHOLDFORMAT
    segments = re.split(r'(<<?|>>?)', arg)
    fullname = segments[0]
    next_is_critical_thresh = False
    thresholds = (None, None, None, None)
    for separator, segment in pairwise(segments[1:]):
        value = float(segment)
        if separator == ">":
            thresholds[0] = value
        elif separator == "<":
            thresholds[1] = value
        elif separator == ">>":
            thresholds[2] = value
        elif separator == "<<":
            thresholds[3] = value

    # Split interface and metric name
    name_parts = fullname.split(".", 1)
    if len(name_parts) != 2:
        raise ValueError("Metric name must consist of interface name and metric name, separated by a single dot.")

    # Construct result
    return MetricsCheck(name_parts[0].translate(TRANSLATE_BACK),
                        name_parts[1].translate(TRANSLATE_BACK),
                        *thresholds)


if __name__ == "__main__":
    main()
