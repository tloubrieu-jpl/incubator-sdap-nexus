import logging
import re
from datetime import datetime
from decimal import Decimal

from pytz import UTC
from webservice.webmodel import RequestParameters
from webservice.webmodel import StatsComputeOptions
from webservice.webmodel import MissingValueException


class NexusRequestObjectTornadoFree(StatsComputeOptions):
    shortNamePattern = re.compile("^[a-zA-Z0-9_\-,\.]+$")
    floatingPointPattern = re.compile('[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?')

    def __init__(self, request_handler):
        self.__log = logging.getLogger(__name__)
        if request_handler is None:
            raise Exception("Request handler cannot be null")
        StatsComputeOptions.__init__(self)

        self._dataset = self._parse_dataset(request_handler)

        self._bounding_box = self._parse_bounding_box(request_handler)

        self._start_time = self._parse_start_time(request_handler)
        self._end_time = self._parse_end_time(request_handler)

        self._apply_seasonal_cycle_filter = self._parse_apply_seasonal_cycle_filter(request_handler)
        self._apply_low_pass_filter = self._parse_apply_low_pass_filter(request_handler)

        self._nparts = self._parse_nparts(request_handler)

        self._content_type = self._parse_content_type(request_handler)

    def get_dataset(self):
        return self._dataset

    def get_bounding_box(self):
        return self._bounding_box

    def get_start_datetime(self):
        if self._start_time:
            return self._start_time
        else:
            raise MissingValueException('missing start time')

    def get_end_datetime(self):
        if self._start_time:
            return self._end_time
        else:
            raise  MissingValueException('missing end time')

    def get_nparts(self):
        return self._nparts

    def get_content_type(self):
        return self._content_type

    def get_apply_seasonal_cycle_filter(self, default=True):
        if self._apply_seasonal_cycle_filter:
            return self._apply_seasonal_cycle_filter
        else:
            return default

    def get_apply_low_pass_filter(self, default=True):
        if self._apply_low_pass_filter:
            return self._apply_low_pass_filter
        else:
            return default


    @staticmethod
    def _parse_dataset(request_handler):
        ds = request_handler.get_argument(RequestParameters.DATASET, None)
        if ds is not None and not NexusRequestObjectTornadoFree.__validate_is_shortname(ds):
            raise ValueError("Invalid shortname")

        return ds

    @staticmethod
    def _parse_bounding_box(request_handler):

        b = request_handler.get_argument("b", '')
        if b:
            min_lon, min_lat, max_lon, max_lat = [float(e) for e in b.split(",")]
        else:
            max_lat = request_handler.get_argument("maxLat", 90)
            max_lat = Decimal(max_lat) if NexusRequestObjectTornadoFree.__validate_is_number(max_lat) else 90

            min_lat = request_handler.get_argument("minLat", -90)
            min_lat = Decimal(min_lat) if NexusRequestObjectTornadoFree.__validate_is_number(min_lat) else -90

            max_lon = request_handler.get_argument("maxLon", 180)
            max_lon = Decimal(max_lon) if NexusRequestObjectTornadoFree.__validate_is_number(max_lon) else 180

            min_lon = request_handler.get_argument("minLon", -90)
            min_lon = Decimal(min_lon) if NexusRequestObjectTornadoFree.__validate_is_number(min_lon) else -90

        return min_lon, min_lat, max_lon, max_lat

    @staticmethod
    def _parse_start_time(request_handler):
        return NexusRequestObjectTornadoFree._parse_time(request_handler, RequestParameters.START_TIME, default=None)

    @staticmethod
    def _parse_end_time(request_handler):
        return NexusRequestObjectTornadoFree._parse_time(request_handler, RequestParameters.END_TIME, default=None)

    @staticmethod
    def _parse_time(request_handler, arg_name, default=None):
        time_str = request_handler.get_argument(arg_name, default)
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError:
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S+00:00").replace(tzinfo=UTC)
            except ValueError:
                dt = datetime.utcfromtimestamp(int(time_str)).replace(tzinfo=UTC)
        return dt

    @staticmethod
    def _parse_apply_seasonal_cycle_filter(request_handler):
        s = request_handler.get_argument(RequestParameters.SEASONAL_CYCLE_FILTER,
                                         default=None)
        return NexusRequestObjectTornadoFree.__parse_boolean(s) if s else None

    @staticmethod
    def _parse_apply_low_pass_filter(request_handler):
        s = request_handler.get_argument(RequestParameters.APPLY_LOW_PASS,
                                         default=None)
        return NexusRequestObjectTornadoFree.__parse_boolean(s) if s else None


    @staticmethod
    def _parse_nparts(request_handler):
        return int(request_handler.get_argument(RequestParameters.NPARTS, 0))

    @staticmethod
    def _parse_content_type(request_handler):
        return request_handler.get_argument(RequestParameters.OUTPUT, "JSON")

    @staticmethod
    def __validate_is_shortname(v):
        if v is None or len(v) == 0:
            return False
        return NexusRequestObjectTornadoFree.shortNamePattern.match(v) is not None

    @staticmethod
    def __validate_is_number(v):
        if v is None or (type(v) == str and len(v) == 0):
            return False
        elif type(v) == int or type(v) == float:
            return True
        else:
            return NexusRequestObjectTornadoFree.floatingPointPattern.match(v) is not None

    @staticmethod
    def __parse_boolean(s):
        return s and s in ['true', '1', 't', 'y', 'yes', 'True', 'T', 'Y', 'Yes', True]



