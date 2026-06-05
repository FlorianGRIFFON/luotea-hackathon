"""ERP scheduled maintenance plans connector."""

from pipeline.bronze.connectors.base import SingleCsvConnector


class MaintenancePlansConnector(SingleCsvConnector):
    source_name = "maintenance_plans"
