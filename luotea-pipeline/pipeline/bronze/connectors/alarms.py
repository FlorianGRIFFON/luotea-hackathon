"""ERP alarms connector."""

from pipeline.bronze.connectors.base import SingleCsvConnector


class AlarmsConnector(SingleCsvConnector):
    source_name = "alarms"
