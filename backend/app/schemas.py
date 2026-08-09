from typing import Optional, List
from pydantic import BaseModel, Field


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    display_name: str


class RouteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class StopOut(BaseModel):
    id: int
    address: str
    complement: Optional[str] = None
    custom_label: Optional[str] = None
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    zipcode: Optional[str] = None
    latitude: float
    longitude: float
    sequence: Optional[int] = None
    status: str
    needs_review: bool
    package_count: int

    class Config:
        from_attributes = True


class RouteOut(BaseModel):
    id: int
    name: str
    status: str
    source_format: Optional[str] = None
    distance_source: Optional[str] = None
    total_distance_km: Optional[float] = None
    total_duration_min: Optional[float] = None
    stops: List[StopOut] = []

    class Config:
        from_attributes = True


class SkipRequest(BaseModel):
    reason: Optional[str] = None
    recalculate: bool = True


class LabelUpdate(BaseModel):
    custom_label: str = Field(..., max_length=120)


class LocationUpdate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class StopAddressUpdate(BaseModel):
    address: str = Field(..., min_length=3, max_length=300)
    complement: Optional[str] = None
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    zipcode: Optional[str] = None


class VerifyResult(BaseModel):
    stop_id: int
    address: str
    original_lat: float
    original_lng: float
    geocoded_lat: Optional[float] = None
    geocoded_lng: Optional[float] = None
    distance_meters: Optional[float] = None
    needs_review: bool
    message: str


class VerifyAddressesResponse(BaseModel):
    route_id: int
    checked: int
    issues_found: int
    source: Optional[str] = None
    results: List[VerifyResult]


class FinishSummary(BaseModel):
    delivered: int
    skipped: int
    pending: int
    total_distance_km: Optional[float]
    elapsed_minutes: Optional[float]
