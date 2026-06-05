"""Shared enumerations for the canonical domain model."""

from enum import IntEnum, StrEnum


class SourceSystem(StrEnum):
    ERP_ALARMS = "erp_alarms"
    ERP_WORK_ORDERS = "erp_work_orders"
    ERP_MAINTENANCE_PLANS = "erp_maintenance_plans"
    SMARTTI_PULSE = "smartti_pulse"
    KONE_OCCUPANCY = "kone_occupancy"
    CLEANING_UTILIZATION = "cleaning_utilization"


class MappingStatus(StrEnum):
    MAPPED = "mapped"
    UNMAPPED = "unmapped"
    PARTIAL = "partial"


class ContractType(StrEnum):
    SP = "SP"  # Siivouspalvelut / Cleaning
    KIPA = "KIPA"  # Kiinteistöpalvelut / Facility services
    KH = "KH"  # Kiinteistöhuolto / Property maintenance
    KT = "KT"  # Kiinteistötekniikka / Technical services


class WorkOrderType(StrEnum):
    SCHEDULED = "EH-työ"
    ON_DEMAND = "Tilaustyö"


class AlarmHwidType(StrEnum):
    ALERTA = "Alerta"
    K2_RECEIVER = "K2 vastaanotin"
    EMAIL_ALERT = "Sähköpostihälytys"


class AlarmType(StrEnum):
    LVIS = "LVIS"
    LINJAVIK = "LINJAVIK"
    HALYT = "HÄLYT"
    INFO = "INFO"
    LVIA = "LVIA"
    PALO = "PALO"
    PALOVIK = "PALOVIK"
    LVI_HALY = "Lvi-häly"


class AlarmPriority(IntEnum):
    FIRE = 1
    RARE = 13
    MEDIUM = 50
    STANDARD = 60
    FIRE_EQUIPMENT = 77
    INFORMATIONAL = 99


class MaintenancePlanState(StrEnum):
    ACTIVE = "Active"
    OBSOLETE = "Obsolete"


class SmarttiNodeType(StrEnum):
    DEVICE = "device"
    SYSTEM = "system"
    BUILDING = "building"


class SmarttiReadingSource(StrEnum):
    ENERKEY = "enerkey"
    SMARTTI_AUTOMATION = "smartti_automation"


class SmarttiIncidentPriority(StrEnum):
    IMMEDIATE = "immediate"
    SIGNIFICANT = "significant"
    ACCORDING_TO_AGREEMENT = "according_to_agreement"


class SmarttiIncidentStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_REVIEW = "awaiting_review"
    RESOLVED = "resolved"


class SmarttiIncidentCategory(StrEnum):
    FAULT = "fault"
    OPTIMIZATION = "optimization"
    ADMINISTRATIVE = "administrative"
    CONDITIONS_DEVIATION = "conditions_deviation"


class OccupancyValueType(StrEnum):
    NORMALIZED = "normalized"
    RAW_COUNT = "raw_count"


class AssetType(StrEnum):
    ROOM = "room"
    DESK = "desk"
    FLOOR = "floor"
    BUILDING = "building"
    DEVICE = "device"
