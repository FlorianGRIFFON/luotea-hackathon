"""Pydantic models for the canonical Silver/Gold domain model.

These schemas define the target shape after Bronze → Silver transforms.
All timestamps are UTC unless noted. Finnish free text is preserved as-is.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.schemas.enums import (
    AlarmHwidType,
    AlarmPriority,
    AlarmType,
    AssetType,
    ContractType,
    MaintenancePlanState,
    MappingStatus,
    OccupancyValueType,
    SmarttiIncidentCategory,
    SmarttiIncidentPriority,
    SmarttiIncidentStatus,
    SmarttiNodeType,
    SmarttiReadingSource,
    SourceSystem,
    WorkOrderType,
)

ModelConfig = ConfigDict(
    frozen=True,
    str_strip_whitespace=True,
    use_enum_values=True,
)


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


class DimCustomer(BaseModel):
    """Canonical customer dimension."""

    model_config = ModelConfig

    customer_id: str = Field(description="Canonical customer ID (e.g. cust_valmet, cust_novaprop)")
    customer_name: str
    erp_customer_no: int | None = None
    region_code: str = "FI"
    currency: str | None = None
    timezone: str = "Europe/Helsinki"
    source_system: SourceSystem


class DimSite(BaseModel):
    """Canonical site/property dimension — the primary join key across sources."""

    model_config = ModelConfig

    site_id: str = Field(description="Canonical site ID from mappings/sites.yaml")
    display_name: str
    customer_id: str
    address: str | None = None
    city: str | None = None
    country: str = "FI"
    timezone: str = "Europe/Helsinki"
    # ERP keys (nullable for NovaProp sites)
    erp_customer_no: int | None = None
    erp_customer_site_no: int | None = None
    # Smartti keys (nullable for Valmet sites)
    smartti_property_id: str | None = None
    smartti_file_slug: str | None = None
    # KONE key
    kone_building_name: str | None = None
    mapping_status: MappingStatus = MappingStatus.MAPPED
    gross_area_m2: float | None = None


class DimContract(BaseModel):
    """Contract type dimension aligned across work orders, alarms, and maintenance."""

    model_config = ModelConfig

    contract_id: str
    contract_type: ContractType
    contract_no: int | None = None
    service_line_fin: str | None = None
    service_line_eng: str | None = None
    site_id: str | None = None


class DimAsset(BaseModel):
    """Room, desk, floor, or building within a site."""

    model_config = ModelConfig

    asset_id: str
    site_id: str | None = None
    asset_name: str
    asset_type: AssetType
    parent_asset_id: str | None = None
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    source_system: SourceSystem
    source_asset_key: str = Field(description="Original name/ID in source system")


class DimEquipment(BaseModel):
    """Hardware device or Smartti node."""

    model_config = ModelConfig

    equipment_id: str
    site_id: str | None = None
    equipment_name: str
    equipment_type: str | None = None
    node_type: SmarttiNodeType | None = None
    hwid: str | None = None
    hwid_type: AlarmHwidType | None = None
    smartti_node_id: str | None = None
    tags: str | None = None
    source_system: SourceSystem


class BridgeSourceAssetMap(BaseModel):
    """Maps external asset/equipment IDs to canonical IDs with confidence."""

    model_config = ModelConfig

    source_system: SourceSystem
    source_key: str
    canonical_asset_id: str | None = None
    canonical_equipment_id: str | None = None
    site_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    effective_from: date | None = None
    effective_to: date | None = None
    mapping_status: MappingStatus


# ---------------------------------------------------------------------------
# Facts — ERP
# ---------------------------------------------------------------------------


class FactWorkOrder(BaseModel):
    """Silver fact: one row per work order."""

    model_config = ModelConfig

    wo_no: int
    site_id: str | None = None
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    customer_no: int
    customer_site_no: int
    customer_worksite_no: str
    contract_type: ContractType
    contract_no: int | None = None
    work_order_type: WorkOrderType
    wo_parent_id: int | None = None
    assignment_type: str | None = None
    priority_id: int | None = Field(default=None, ge=1, le=6)
    work_description: str | None = None
    work_order_description: str
    work_order_performed_action: str | None = None
    work_type_fin: str
    work_type_eng: str
    pm_no: str | None = None
    pm_action_descr: str | None = None
    work_started_at_utc: datetime
    work_finished_at_utc: datetime
    work_finished_days: float
    sla_required_start_at_utc: datetime | None = None
    sla_required_end_at_utc: datetime | None = None
    is_sla_violation: bool
    worktime_hours: float | None = None
    is_invoicable: bool
    is_subcontractor_work: bool
    source_system: Literal[SourceSystem.ERP_WORK_ORDERS] = SourceSystem.ERP_WORK_ORDERS
    source_file: str | None = None


class FactAlarm(BaseModel):
    """Silver fact: one row per alarm event (location fan-out preserved)."""

    model_config = ModelConfig

    alert_event_id: int
    alert_id: int
    site_id: str | None = None
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    customer_no: int
    customer_site_no: int
    contract_no: int
    event_time_utc: datetime
    event_type: str
    hwid: str
    hwid_type: AlarmHwidType
    loop: str | None = None
    alert_type: AlarmType | None = None
    priority: AlarmPriority
    is_log_only: bool = False
    event_description: str
    workorder_no: int | None = None
    has_work_order: bool = False
    event_closed_at_utc: datetime | None = None
    location_id: int
    location_table_id: int
    iva_no: str
    status: str
    source_system: Literal[SourceSystem.ERP_ALARMS] = SourceSystem.ERP_ALARMS
    source_file: str | None = None


class FactMaintenancePlan(BaseModel):
    """Silver fact: deduplicated maintenance plan (one row per PM_NO)."""

    model_config = ModelConfig

    pm_no: str
    site_id: str | None = None
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    contract_type: ContractType
    customer_no: int
    customer_site_no: int
    customer_worksite_no: str
    action_descr: str
    action_descr_eng: str
    description: str | None = None
    description_eng: str | None = None
    priority_id: int = Field(ge=2, le=5)
    interval: int | None = None
    interval_unit: str | None = None
    plan_hrs: float | None = None
    start_date: date | None = None
    valid_from: date | None = None
    objstate: MaintenancePlanState
    last_updated_utc: datetime
    source_system: Literal[SourceSystem.ERP_MAINTENANCE_PLANS] = (
        SourceSystem.ERP_MAINTENANCE_PLANS
    )
    source_file: str | None = None


# ---------------------------------------------------------------------------
# Facts — IoT / third-party
# ---------------------------------------------------------------------------


class FactSensorReading(BaseModel):
    """Exploded Smartti reading: one row per (property, metric, meter, timestamp)."""

    model_config = ModelConfig

    reading_id: str = Field(description="Surrogate key: hash(property_id, metric, key, t)")
    site_id: str | None = None
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    property_id: str
    parent_property_id: str | None = None
    metric: str
    meter_key: str
    timestamp_utc: datetime
    value: float
    unit: str
    source: SmarttiReadingSource
    source_system: Literal[SourceSystem.SMARTTI_PULSE] = SourceSystem.SMARTTI_PULSE


class FactIncident(BaseModel):
    """Unified incident from Smartti (ERP alarms map to FactAlarm separately)."""

    model_config = ModelConfig

    incident_id: str
    site_id: str | None = None
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    property_id: str
    node_id: str | None = None
    created_at_utc: datetime
    updated_at_utc: datetime
    event_type: str
    priority: SmarttiIncidentPriority
    status: SmarttiIncidentStatus
    category: SmarttiIncidentCategory
    points: float
    description: str
    is_internal: bool = False
    include_in_report: bool = True
    is_resolved: bool = False
    source_system: Literal[SourceSystem.SMARTTI_PULSE] = SourceSystem.SMARTTI_PULSE


class FactOccupancy(BaseModel):
    """Exploded KONE occupancy: one row per (building, month, weekday, floor, hour)."""

    model_config = ModelConfig

    occupancy_id: str = Field(description="Surrogate key: hash(building, month, weekday, floor, hour, value_type)")
    site_id: str | None = None
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    building_name: str
    year: int
    month: int = Field(ge=1, le=12)
    weekday: int = Field(ge=1, le=7, description="1=Monday … 7=Sunday")
    floor: str
    floor_id: int
    hour: int = Field(ge=0, le=23)
    occupancy_value: float
    value_type: OccupancyValueType
    site_connection_ok: bool | None = None
    source_system: Literal[SourceSystem.KONE_OCCUPANCY] = SourceSystem.KONE_OCCUPANCY


class FactUtilization(BaseModel):
    """Unpivoted room/desk utilization: one row per (asset, date)."""

    model_config = ModelConfig

    utilization_id: str = Field(description="Surrogate key: hash(asset_name, date)")
    site_id: str | None = None
    mapping_status: MappingStatus = MappingStatus.UNMAPPED
    asset_name: str
    asset_id: str | None = None
    utilization_date: date
    utilization_pct: float = Field(ge=0.0, le=100.0)
    source_system: Literal[SourceSystem.CLEANING_UTILIZATION] = (
        SourceSystem.CLEANING_UTILIZATION
    )
    source_file: str | None = None


# ---------------------------------------------------------------------------
# Gold (preview schemas — populated in Phase 5)
# ---------------------------------------------------------------------------


class SiteDailySignals(BaseModel):
    """Gold mart: one row per site × date with unified operational signals."""

    model_config = ModelConfig

    site_id: str
    signal_date: date
    alarm_count: int = 0
    fire_alarm_count: int = 0
    hvac_alarm_count: int = 0
    open_work_orders: int = 0
    sla_violations: int = 0
    avg_co2_ppm: float | None = None
    avg_indoor_temp_c: float | None = None
    electricity_kwh: float | None = None
    heating_mwh: float | None = None
    avg_room_utilization_pct: float | None = None
    avg_desk_utilization_pct: float | None = None
    avg_elevator_occupancy: float | None = None
    incident_count: int = 0
    unresolved_incident_count: int = 0
    as_of_date: date | None = None


class EventTimelineEntry(BaseModel):
    """Gold view: unified operational event stream."""

    model_config = ModelConfig

    event_id: str
    site_id: str | None = None
    asset_id: str | None = None
    event_type: str
    severity: str | None = None
    timestamp_utc: datetime
    description: str | None = None
    source_system: SourceSystem
    source_record_id: str
