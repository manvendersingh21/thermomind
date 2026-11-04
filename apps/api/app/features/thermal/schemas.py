"""Pydantic models for the thermal-monitoring feature (feature-local; not part of the shared contract).

Every output is derived from a SIMULATED thermal feed computed from the real UCI load proxy (TEY, MWh per
hourly sample) and the real ambient temperature (AT, °C). No thermal sensor data exists in this project.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROVENANCE = "simulated_from_real_load"
Provenance = Literal["simulated_from_real_load"]

AssetId = Literal["GEN", "GCB", "GSU", "HVSG", "BUS"]
ThermalScenario = Literal["none", "T01_HOT_CONNECTION"]
DemandProfile = Literal["flat", "diurnal_datacenter"]
AssetState = Literal["normal", "approaching", "alarm", "limit"]
FlagType = Literal[
    "approaching_alarm",
    "above_alarm",
    "above_limit",
    "exceeded_alarm_in_window",
    "rising_faster_than_peers",
    "hot_connection_pattern",
]
Severity = Literal["info", "watch", "warning", "high"]

BANNER = (
    "Simulated thermal feed derived from real load and ambient data — no thermal sensors are connected; "
    "advisory only; no load or breaker is changed by this software."
)
READ_ONLY_SUFFIX = "no action is taken by this software."


class ThermalAssumptions(BaseModel):
    """Every number here is an ASSUMPTION input (not a measurement). Defaults are documented in
    docs/THERMAL_MONITORING.md. Ratings are expressed as hourly energy at nameplate (MWh per hourly sample)
    so that the load ratio K = TEY / rating stays in the published unit (TEY is never converted to MW)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # ratings (load ratio K = TEY / rating)
    generator_rated_mwh: float = Field(180.0, gt=10, le=5000, description="GEN + generator breaker rating, MWh per hourly sample")
    transformer_rated_mwh: float = Field(180.0, gt=10, le=5000, description="step-up transformer rating, MWh per hourly sample")
    hv_rated_mwh: float = Field(200.0, gt=10, le=5000, description="HV switchgear + busbar rating, MWh per hourly sample")
    indoor_ambient_offset_k: float = Field(5.0, ge=0, le=30, description="enclosure/room temperature above outdoor AT (GCB, HVSG, BUS)")
    approach_margin_k: float = Field(10.0, gt=0, le=50, description="'approaching' band below the alarm temperature")

    # transformer, IEEE C57.91 Clause 7 style
    top_oil_rise_rated_k: float = Field(55.0, gt=0, le=100, description="Δθ_TO,R top-oil rise over ambient at rated load")
    hot_spot_gradient_rated_k: float = Field(25.0, gt=0, le=60, description="Δθ_H,R hot-spot rise over top oil at rated load")
    loss_ratio_r: float = Field(5.0, gt=0, le=30, description="R = load losses / no-load losses at rated load")
    exponent_n: float = Field(0.8, ge=0.5, le=1.2, description="top-oil exponent n (ONAN/ONAF ≈ 0.8–0.9)")
    exponent_m: float = Field(0.8, ge=0.5, le=1.2, description="winding exponent m (ONAN/ONAF ≈ 0.8)")
    tau_top_oil_h: float = Field(3.0, gt=0, le=24, description="top-oil time constant τ_TO, hours")
    tau_hot_spot_h: float = Field(0.1, gt=0, le=2, description="winding hot-spot time constant τ_H, hours")
    transformer_hot_spot_alarm_c: float = Field(110.0, gt=0, le=250)
    transformer_hot_spot_limit_c: float = Field(120.0, gt=0, le=250)
    transformer_top_oil_limit_c: float = Field(105.0, gt=0, le=200)
    normal_insulation_life_h: float = Field(180000.0, gt=1000, le=1_000_000, description="IEEE C57.91 normal insulation life basis")

    # generator stator (proxy)
    generator_rated_rise_k: float = Field(80.0, gt=0, le=150)
    generator_alarm_c: float = Field(130.0, gt=0, le=250)
    generator_limit_c: float = Field(155.0, gt=0, le=250)

    # switchgear contacts (GCB and HVSG) and busbar
    contact_rated_rise_k: float = Field(65.0, gt=0, le=120)
    contact_alarm_c: float = Field(95.0, gt=0, le=250)
    contact_limit_c: float = Field(105.0, gt=0, le=250)
    busbar_rated_rise_k: float = Field(30.0, gt=0, le=120)
    busbar_alarm_c: float = Field(80.0, gt=0, le=250)
    busbar_limit_c: float = Field(90.0, gt=0, le=250)

    # synthetic defect (only used when scenario == T01_HOT_CONNECTION)
    hot_connection_growth: float = Field(1.0, gt=0, le=5, description="SYNTHETIC: rise coefficient grows from 1× to (1+g)× over the window")

    @model_validator(mode="after")
    def _alarm_below_limit(self) -> "ThermalAssumptions":
        pairs = [
            ("transformer_hot_spot", self.transformer_hot_spot_alarm_c, self.transformer_hot_spot_limit_c),
            ("generator", self.generator_alarm_c, self.generator_limit_c),
            ("contact", self.contact_alarm_c, self.contact_limit_c),
            ("busbar", self.busbar_alarm_c, self.busbar_limit_c),
        ]
        for name, alarm, limit in pairs:
            if alarm >= limit:
                raise ValueError(f"{name} alarm ({alarm}) must be below its limit ({limit})")
        return self


class ThermalEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    dataset_id: str = Field("ds_uci_551", max_length=128)
    year: int = Field(2014, ge=2000, le=2100)
    start: int = Field(1200, ge=0, le=100_000, description="first row_index (inclusive)")
    end: int = Field(1320, ge=1, le=100_000, description="last row_index (exclusive)")
    assumptions: ThermalAssumptions = Field(default_factory=ThermalAssumptions)
    scenario: ThermalScenario = "none"
    scenario_seed: int = Field(42, ge=0, le=2**31 - 1)
    demand_multiplier: Optional[float] = Field(None, ge=0.5, le=2.0, description="what-if load multiplier, e.g. 1.15 = +15 %")
    demand_profile: DemandProfile = "flat"


class AssetInfo(BaseModel):
    asset_id: AssetId
    name: str
    kind: str
    order: int
    group: Literal["rotating", "connection", "transformer"]
    temperature_label: str
    model: str
    standard_ref: str
    rating_param: str
    rise_param: Optional[str] = None
    alarm_param: str
    limit_param: str


class DemandProfileInfo(BaseModel):
    profile: DemandProfile
    description: str


class ThermalAssetsResponse(BaseModel):
    assets: list[AssetInfo]
    default_assumptions: ThermalAssumptions
    scenarios: list[ThermalScenario]
    demand_profiles: list[DemandProfileInfo]
    provenance: Provenance = PROVENANCE
    banner: str = BANNER


class WindowInfo(BaseModel):
    source_year: int
    start: int
    end: int
    n_samples: int
    note: str = "ordered hourly-aggregate samples without timestamps; consecutive rows are treated as 1 h steps"


class AssetStatus(BaseModel):
    asset_id: AssetId
    name: str
    state: AssetState
    current_c: float
    load_ratio_k: float
    ambient_c: float
    alarm_c: float
    limit_c: float
    margin_to_alarm_k: float
    margin_to_limit_k: float
    peak_c: float
    peak_row_index: int
    trend_k_per_sample: Optional[float] = None
    trend_window_samples: int = 24
    samples_above_alarm: int
    samples_above_limit: int
    rise_index: Optional[float] = None  # load-corrected rise / rated rise (connection group only)
    rise_index_drift: Optional[float] = None
    top_oil_c: Optional[float] = None
    top_oil_limit_c: Optional[float] = None
    synthetic: bool = False
    provenance: Provenance = PROVENANCE


class ThermalFlag(BaseModel):
    asset_id: AssetId
    flag: FlagType
    severity: Severity
    message: str
    synthetic: bool = False
    provenance: Provenance = PROVENANCE


class Advisory(BaseModel):
    asset_id: AssetId
    kind: Literal["margin", "hot_connection", "trend", "demand_scenario"]
    severity: Severity
    text: str
    read_only: bool = True
    synthetic: bool = False
    what_if: bool = False
    provenance: Provenance = PROVENANCE


class Ageing(BaseModel):
    asset_id: AssetId = "GSU"
    method: str = "IEEE C57.91 Clause 7 ageing acceleration factor F_AA = exp(15000/383 − 15000/(θ_H+273))"
    current_faa: float
    equivalent_faa: float
    loss_of_life_h: float
    loss_of_life_pct: float
    window_hours: int
    normal_insulation_life_h: float
    extrapolated_loss_of_life_pct_per_year: float
    extrapolation_label: str = (
        "EXTRAPOLATED: assumes this window's equivalent ageing rate persists for 8760 h; not a forecast"
    )
    provenance: Provenance = PROVENANCE


class SeriesPoint(BaseModel):
    row_index: int
    ambient_c: float
    load_mwh: float
    load_ratio_k: float
    GEN: float
    GCB: float
    GSU: float
    GSU_TOP_OIL: float
    HVSG: float
    BUS: float
    lol_cum_pct: float
    GSU_whatif: Optional[float] = None  # hot spot under the what-if demand scenario (when applied)
    lol_cum_pct_whatif: Optional[float] = None


class LimitLine(BaseModel):
    asset_id: AssetId
    alarm_c: float
    limit_c: float


class DemandImpactRow(BaseModel):
    asset_id: AssetId
    baseline_peak_c: float
    scenario_peak_c: float
    delta_peak_k: float
    baseline_samples_above_alarm: int
    scenario_samples_above_alarm: int
    baseline_samples_above_limit: int
    scenario_samples_above_limit: int


class DemandScenario(BaseModel):
    applied: bool
    multiplier: float
    profile: DemandProfile
    description: str
    notional_hour_note: Optional[str] = None
    samples_above_nameplate_baseline: int = 0
    samples_above_nameplate_scenario: int = 0
    impact: list[DemandImpactRow] = Field(default_factory=list)
    scenario_status: list["AssetStatus"] = Field(default_factory=list)
    baseline_loss_of_life_pct: Optional[float] = None
    scenario_loss_of_life_pct: Optional[float] = None
    caveat: str = (
        "What-if only: scales the real load proxy; the gas turbine's own capability limit, cooling-stage "
        "changes and grid constraints are not modelled."
    )
    what_if: bool = True


class SyntheticDefect(BaseModel):
    scenario: Literal["T01_HOT_CONNECTION"]
    asset_id: AssetId
    description: str
    growth: float
    seed: int
    synthetic: bool = True


class ThermalEvaluateResponse(BaseModel):
    dataset_id: str
    window: WindowInfo
    provenance: Provenance = PROVENANCE
    synthetic: bool
    scenario: ThermalScenario
    synthetic_defect: Optional[SyntheticDefect] = None
    demand: DemandScenario
    status: list[AssetStatus]
    flags: list[ThermalFlag]
    advisories: list[Advisory]
    ageing: Ageing
    limits: list[LimitLine]
    series: list[SeriesPoint]
    downsample_factor: int
    assumptions: ThermalAssumptions
    banner: str = BANNER
    model_note: str = (
        "Planning/awareness model, not a measurement: temperatures are computed from real TEY and AT with "
        "assumed ratings and rises (see docs/THERMAL_MONITORING.md)."
    )
