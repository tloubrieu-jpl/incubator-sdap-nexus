from collections import OrderedDict
import logging

metrics_logger = logging.getLogger(__name__)


class MetricsRecord(object):
    def __init__(self, fields):
        self._fields = OrderedDict()
        for field in fields:
            self._fields[field.key] = field

    def record_metrics(self, **kwargs):
        for field_key, addend in kwargs.items():
            if field_key in self._fields:
                self._fields[field_key].add(addend)

    def print_metrics(self, logger=None):
        if not logger:
            logger = metrics_logger

        logging_lines = ["{description}: {value}".format(description=field.description,
                                                         value=field.value()) for field in self._fields.values()]
        logger.info('\n'.join(logging_lines))

    def write_metrics(self):
        raise NotImplementedError
