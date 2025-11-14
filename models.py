#!/usr/bin/python3
# -*- coding: utf-8 -*-

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    token_type: str


class LocationData(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude between -90 and 90")
    lng: float = Field(
        ..., ge=-180, le=180, description="Longitude between -180 and 180"
    )
    storefront_direction: str = Field(
        default="north", description="Direction the storefront faces"
    )
    day: Optional[str] = Field(
        default=None, description="Day of week (e.g., Monday, Tuesday)"
    )
    time: Optional[str] = Field(
        default=None, description="Time in format like 10PM, 8:30AM"
    )
    zoom: Optional[int] = Field(default=18, description="Map URL Zoom value")


class LocationRequest(BaseModel):
    save_to_static: bool = Field(
        default=False, description="Save screenshot to static path"
    )
    save_to_db: bool = Field(default=False, description="Save results to database")
    location: LocationData = Field(..., description="Location data for analysis")


class LocationResponse(BaseModel):
    request_id: str
    result: Dict[str, Any]
    saved_to_db: bool = Field(
        default=False, description="Whether result was saved to database"
    )
    saved_to_static: bool = Field(
        default=False, description="Whether screenshot was saved to static files"
    )


class MultiLocationRequest(BaseModel):
    save_to_static: bool = Field(
        default=False, description="Save screenshots to static path"
    )
    save_to_db: bool = Field(default=False, description="Save results to database")
    locations: List[LocationData] = Field(
        ..., min_items=1, max_items=20, description="List of locations to analyze"
    )


class MultiLocationResponse(BaseModel):
    request_id: str
    locations_count: int
    completed: int
    result: List[Dict[str, Any]]
    saved_to_db: bool = Field(
        default=False, description="Whether results were saved to database"
    )
    saved_to_static: bool = Field(
        default=False, description="Whether screenshots were saved to static files"
    )
    error: Optional[str] = None
