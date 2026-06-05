"""ERP work orders connector."""

from pipeline.bronze.connectors.base import SingleCsvConnector


class WorkOrdersConnector(SingleCsvConnector):
    source_name = "work_orders"
