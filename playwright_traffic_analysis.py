#!/usr/bin/python3
# -*- coding: utf-8 -*-


import math
import os
import re
import shutil
import time
from collections import Counter
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np
from PIL import Image
from playwright.async_api import BrowserContext, Page, ViewportSize

from config import logger

# Traffic color ranges in RGB - wider, more tolerant ranges
TRAFFIC_COLORS = {
    "dark_red": [(140, 0, 0), (200, 70, 70)],  # Wider range for dark red
    "red": [(220, 50, 40), (255, 110, 90)],  # Wider range for red
    "yellow": [(230, 170, 40), (255, 230, 100)],  # Wider range for yellow/orange
    "green": [(0, 180, 120), (60, 255, 190)],  # Wider range for green
    "gray": [(160, 170, 180), (200, 210, 220)],  # Slightly wider range for gray
}

TRAFFIC_SCORES = {"dark_red": 100, "red": 100, "yellow": 70, "green": 30, "gray": 0}


# Direction mappings for storefront orientation
DIRECTION_ANGLES = {
    "north": 0,
    "n": 0,
    "northeast": 45,
    "ne": 45,
    "east": 90,
    "e": 90,
    "southeast": 135,
    "se": 135,
    "south": 180,
    "s": 180,
    "southwest": 225,
    "sw": 225,
    "west": 270,
    "w": 270,
    "northwest": 315,
    "nw": 315,
}

DAY_MAP = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}

TIME_MAP = {"8:30AM": 16, "6PM": 75, "10PM": 99.9}

TRAFFIC_SCREENSHOTS_PATH = os.path.join(
    os.path.dirname(__file__), "traffic_screenshots"
)
TRAFFIC_SCREENSHOTS_STATIC_PATH = os.path.join(
    os.path.dirname(__file__),
    "static",
    "images",
    "traffic_screenshots",
)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"


def sec(timeout: int | float) -> int | float:
    return timeout * 1000


def google_map_url(lat: float, lng: float, *, zoom: int = 18) -> str:
    return f"https://www.google.com/maps/@{lat},{lng},{zoom}z/data=!5m1!1e1?hl=en&gl=us"


# ------------------------ image processing section ----------------------#
def classify_traffic_color(rgb: Tuple[int, int, int]) -> str:
    """Classify RGB color into traffic categories"""
    for traffic_type, (min_rgb, max_rgb) in TRAFFIC_COLORS.items():
        # Check if color is within range
        if all(
            min_val <= rgb[i] <= max_val
            for i, (min_val, max_val) in enumerate(zip(min_rgb, max_rgb))
        ):
            return traffic_type
    return "gray"  # Default to gray if no range matches


def add_pin_to_image(image_path: str, storefront_direction: str = "north") -> str:
    """Add a pin marker and directional cone to the center of the image for verification"""
    try:

        # Add a small delay to ensure the file is not locked
        # time.sleep(0.2)

        # Load the image
        image = Image.open(image_path)

        # Get image center
        width, height = image.size
        center_x, center_y = width // 2, height // 2

        # Add directional cone for storefront direction
        _add_directional_arrow(image, center_x, center_y, storefront_direction)

        # Generate pinned image path
        pinned_path = image_path.replace(".png", "_pinned.png")

        # Ensure we close the original image before saving
        image_copy = image.copy()
        image.close()

        # Save the modified image
        image_copy.save(pinned_path)
        image_copy.close()

        # Add a small delay to ensure the file is fully written
        # time.sleep(0.5)

        logger.info(f"Pin and directional cone added to image: {pinned_path}")
        return pinned_path

    except Exception as e:
        logger.error(f"Failed to add pin to image: {e}")
        return image_path  # Return original path if pin addition fails


def _add_directional_arrow(
    image: Image.Image, center_x: int, center_y: int, direction: str
):
    """Draw a pin with a directional cone pointing towards the storefront direction"""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)

    # Pin head (smaller circle)
    pin_head_size = 8
    draw.ellipse(
        [
            center_x - pin_head_size,
            center_y - pin_head_size,
            center_x + pin_head_size,
            center_y + pin_head_size,
        ],
        fill="purple",
        outline="black",
        width=1,
    )

    # Directional cone
    direction_angle = DIRECTION_ANGLES.get(direction.lower(), 0)
    # angle_rad = math.radians(direction_angle)

    # Cone parameters
    cone_length = 52  # 75% larger cone
    cone_width_degrees = 25  # Half-width of the cone's base in degrees

    # Calculate the three points of the cone
    # Point 1: Tip of the cone (at the center of the circle)
    p1 = (center_x, center_y)

    # Point 2: Base of the cone
    angle2 = math.radians(direction_angle - cone_width_degrees)
    p2 = (
        center_x + cone_length * math.sin(angle2),
        center_y - cone_length * math.cos(angle2),
    )

    # Point 3: Base of the cone
    angle3 = math.radians(direction_angle + cone_width_degrees)
    p3 = (
        center_x + cone_length * math.sin(angle3),
        center_y - cone_length * math.cos(angle3),
    )

    draw.polygon([p1, p2, p3], fill="hotpink", outline="black")

    logger.info(f"Directional cone added pointing {direction}")


def _analyze_annular_zone(
    image_array: np.ndarray,
    center_x: int,
    center_y: int,
    height: int,
    width: int,
    inner_radius: int,
    outer_radius: int,
    zone_name: str,
    traffic_analysis: Dict[str, Any],
    excluded_pixels: Optional[set[Tuple[int, int]]] = None,
):
    """
    Analyzes an annular (ring-shaped) zone for traffic colors, excluding specified pixels.
    """
    if excluded_pixels is None:
        excluded_pixels = set()

    zone_colors = []
    pixels_in_zone = 0

    for y in range(
        max(0, center_y - outer_radius), min(height, center_y + outer_radius + 1)
    ):
        for x in range(
            max(0, center_x - outer_radius), min(width, center_x + outer_radius + 1)
        ):
            distance = math.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
            if (
                inner_radius < distance <= outer_radius
                and (x, y) not in excluded_pixels
            ):
                rgb = tuple(image_array[y, x][:3])
                color_type = classify_traffic_color(rgb)
                zone_colors.append(color_type)
                pixels_in_zone += 1

    # Calculate zone score, ignoring gray pixels
    non_gray_colors = [c for c in zone_colors if c != "gray"]
    if non_gray_colors:
        color_counts = Counter(non_gray_colors)
        zone_score = sum(
            count * TRAFFIC_SCORES[color] for color, count in color_counts.items()
        ) / len(non_gray_colors)
    else:
        zone_score = 0  # If only gray pixels, score is 0

    traffic_analysis["area_scores"][zone_name] = {
        "score": zone_score,
        "pixels": pixels_in_zone,
        "colors": dict(Counter(zone_colors)),  # Report all colors, even gray
    }

    # Update overall color distribution
    for color, count in Counter(zone_colors).items():
        traffic_analysis["color_distribution"][color] += count
    logger.info(
        f"Analyzed {zone_name} zone: Score={zone_score}, Pixels={pixels_in_zone}"
    )


def find_storefront_traffic(
    image_array: np.ndarray,
    center_x: int,
    center_y: int,
    storefront_direction: str,
    max_distance: int = 50,
) -> Tuple[Dict[str, Any], set[Tuple[int, int]]]:
    """
    Find the closest traffic color to the center point using a cone search.

    Args:
        image_array: The image as a numpy array.
        center_x, center_y: Center coordinates of the image.
        storefront_direction: Direction the storefront faces (e.g., 'north', 'northeast').
        max_distance: Maximum distance to search in pixels (default 50m).

    Returns:
        A tuple containing:
        - A dictionary with the storefront analysis results.
        - A set of (x, y) coordinates of pixels checked within the cone.
    """
    height, width = image_array.shape[:2]
    checked_cone_pixels = set()

    # Define angle ranges for cone search based on storefront direction
    # Cone width is 60 degrees (30 degrees on each side of the center direction)
    direction_angle = DIRECTION_ANGLES.get(storefront_direction.lower(), 0)
    min_angle = (direction_angle - 30 + 360) % 360
    max_angle = (direction_angle + 30) % 360

    # Adjust for wrapping around 0/360 degrees
    angle_range = []
    if min_angle < max_angle:
        angle_range = range(min_angle, max_angle + 1, 5)
    else:  # Case where cone crosses the 0/360 boundary (e.g., north: 330-30)
        angle_range = list(range(min_angle, 360, 5)) + list(range(0, max_angle + 1, 5))

    # Search in an expanding cone for the first non-gray pixel
    for distance in range(1, max_distance + 1):  # Include max_distance
        for angle in angle_range:
            angle_rad = math.radians(angle)
            x = int(
                center_x + distance * math.sin(angle_rad)
            )  # Swapped sin/cos for correct orientation
            y = int(
                center_y - distance * math.cos(angle_rad)
            )  # Y is inverted in image coordinates

            if 0 <= x < width and 0 <= y < height:
                checked_cone_pixels.add((x, y))  # Add pixel to set of checked pixels
                rgb = tuple(image_array[y, x][:3])
                color_type = classify_traffic_color(rgb)

                if color_type != "gray":
                    logger.info(
                        f"Storefront traffic found: {color_type} at distance {distance}px in {storefront_direction} cone"
                    )
                    return {
                        "found": True,
                        "color": color_type,
                        "distance": distance,
                        "score": TRAFFIC_SCORES[color_type],
                    }, checked_cone_pixels

    # If no traffic is found, return default gray score and all checked pixels
    return {
        "found": False,
        "color": "gray",
        "distance": max_distance,
        "score": 0,
    }, checked_cone_pixels


def analyze_traffic_in_image(
    image_path: str,
    center_lat: float,
    center_lng: float,
    storefront_direction: str = "north",
) -> Dict[str, Any]:
    """Analyze traffic colors in the screenshot image with circular storefront detection"""
    try:
        # Load the image
        image = Image.open(image_path)
        image_array = np.array(image)

        height, width = image_array.shape[:2]
        center_x, center_y = width // 2, height // 2

        # Define analysis zones (in pixels from center)
        # Zoom level 18 corresponds to approximately 20m scale
        pixels_per_meter = 1.5  # Adjusted for zoom level 18 (20m scale)

        # Define radii for distinct annular zones
        storefront_cone_radius_px = int(50 * pixels_per_meter)
        full_50m_circle_radius_px = int(
            50 * pixels_per_meter
        )  # Full 50m circle for the first area score
        outer_100m_zone_radius_px = int(
            100 * pixels_per_meter
        )  # Outer radius for 50m-100m ring
        outer_150m_zone_radius_px = int(
            150 * pixels_per_meter
        )  # Outer radius for 100m-150m ring

        traffic_analysis = {
            "storefront_score": 0,
            "area_scores": {},
            "total_pixels_analyzed": 0,
            "color_distribution": {color: 0 for color in TRAFFIC_COLORS.keys()},
            "storefront_details": {},
        }

        # Find storefront traffic using cone search
        storefront_result, cone_pixels_checked = find_storefront_traffic(
            image_array,
            center_x,
            center_y,
            storefront_direction,
            storefront_cone_radius_px,
        )

        traffic_analysis["storefront_details"] = storefront_result
        traffic_analysis["storefront_score"] = storefront_result["score"]

        # Update color distribution with storefront findings
        if storefront_result["found"]:
            traffic_analysis["color_distribution"][storefront_result["color"]] += 1

        # Analyze the 50m area (full circle excluding the cone)
        zone_colors_50m_full_circle = []
        pixels_in_zone_50m_full_circle = 0
        for y in range(
            max(0, center_y - full_50m_circle_radius_px),
            min(height, center_y + full_50m_circle_radius_px + 1),
        ):
            for x in range(
                max(0, center_x - full_50m_circle_radius_px),
                min(width, center_x + full_50m_circle_radius_px + 1),
            ):
                distance = math.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
                if (
                    distance <= full_50m_circle_radius_px
                    and (x, y) not in cone_pixels_checked
                ):
                    rgb = tuple(image_array[y, x][:3])
                    color_type = classify_traffic_color(rgb)
                    zone_colors_50m_full_circle.append(color_type)
                    pixels_in_zone_50m_full_circle += 1

        non_gray_colors_50m_full_circle = [
            c for c in zone_colors_50m_full_circle if c != "gray"
        ]
        if non_gray_colors_50m_full_circle:
            color_counts_50m_full_circle = Counter(non_gray_colors_50m_full_circle)
            zone_score_50m_full_circle = sum(
                count * TRAFFIC_SCORES[color]
                for color, count in color_counts_50m_full_circle.items()
            ) / len(non_gray_colors_50m_full_circle)
        else:
            zone_score_50m_full_circle = 0

        traffic_analysis["area_scores"]["50m"] = {
            "score": zone_score_50m_full_circle,
            "pixels": pixels_in_zone_50m_full_circle,
            "colors": dict(Counter(zone_colors_50m_full_circle)),
        }
        for color, count in Counter(zone_colors_50m_full_circle).items():
            traffic_analysis["color_distribution"][color] += count
        logger.info(
            f"Analyzed 50m full circle (excluding cone) zone: Score={zone_score_50m_full_circle}, Pixels={pixels_in_zone_50m_full_circle}"
        )

        # Analyze the 100m area (annular region from 50m to 100m)
        _analyze_annular_zone(
            image_array,
            center_x,
            center_y,
            height,
            width,
            full_50m_circle_radius_px,
            outer_100m_zone_radius_px,
            "100m",
            traffic_analysis,
        )

        # Analyze the 150m area (annular region from 100m to 150m)
        _analyze_annular_zone(
            image_array,
            center_x,
            center_y,
            height,
            width,
            outer_100m_zone_radius_px,
            outer_150m_zone_radius_px,
            "150m",
            traffic_analysis,
        )

        traffic_analysis["total_pixels_analyzed"] = sum(
            traffic_analysis["color_distribution"].values()
        )

        return traffic_analysis

    except Exception as e:
        logger.error(f"Failed to analyze traffic in image: {e}")
        return {}


def calculate_final_traffic_score(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate final traffic score based on analysis"""
    if not analysis:
        return {"score": 0, "details": "Analysis failed"}

    # 60% weight for storefront traffic
    storefront_score = analysis.get("storefront_score", 0)
    storefront_weight = 0.1  # lowered until storefront direction can be extracted
    logger.info(f"Storefront Score: {storefront_score}, Weight: {storefront_weight}")

    # 40% weight for surrounding area traffic with distance multipliers
    area_weight = 0.9
    area_score = 0
    total_weighted_pixels = 0

    area_scores = analysis.get("area_scores", {})
    multipliers = {"50m": 1.0, "100m": 0.5, "150m": 0.25}

    logger.info("Calculating area scores:")
    for zone, multiplier in multipliers.items():
        if zone in area_scores:
            zone_data = area_scores[zone]
            zone_score = zone_data.get("score", 0)
            zone_pixels = zone_data.get("pixels", 0)

            logger.info(
                f"  Zone '{zone}': Score={zone_score}, Pixels={zone_pixels}, Multiplier={multiplier}"
            )

            weighted_contribution = zone_score * multiplier * zone_pixels
            area_score += weighted_contribution
            total_weighted_pixels += zone_pixels * multiplier
            logger.info(
                f"    Weighted contribution for '{zone}': {weighted_contribution}"
            )

    if total_weighted_pixels > 0:
        area_score = area_score / total_weighted_pixels
        logger.info(f"Total weighted pixels for area: {total_weighted_pixels}")
        logger.info(f"Final calculated area score: {area_score}")
    else:
        area_score = 0  # If only gray pixels, score is 0
        logger.info("No non-gray pixels in surrounding area, area score is 0.")

    # Calculate final score
    final_score = (storefront_score * storefront_weight) + (area_score * area_weight)
    logger.info(
        f"Final Score Calculation: ({storefront_score} * {storefront_weight}) + ({area_score} * {area_weight}) = {final_score}"
    )

    return {
        "score": round(final_score, 2),
        "storefront_score": storefront_score,
        "area_score": round(area_score, 2),
        "storefront_weight": storefront_weight,
        "area_weight": area_weight,
        "total_pixels_analyzed": analysis.get("total_pixels_analyzed", 0),
        "color_distribution": analysis.get("color_distribution", {}),
        "area_details": area_scores,
    }


# ------------------------ end image processing section ----------------------#


async def save_traffic_screenshot(
    page: Page,
    lat: float,
    lng: float,
    day_of_week: Optional[str] = None,
    target_time: Optional[str] = None,
) -> str:

    safe_day_of_week = (
        str(day_of_week).replace(" ", "_") if day_of_week is not None else "no_day"
    )
    safe_target_time = (
        str(target_time).replace(":", "-") if target_time is not None else "no_time"
    )

    # os.makedirs(TRAFFIC_SCREENSHOTS_PATH, exist_ok=True)
    screenshot_path = os.path.join(
        TRAFFIC_SCREENSHOTS_PATH,
        f"traffic_{lat}_{lng}_{safe_day_of_week}_{safe_target_time}.png",
    )

    try:
        await page.screenshot(path=screenshot_path, type="png")
        logger.info(f"Screenshot captured at 20m zoom level: {screenshot_path}")
        return screenshot_path
    except Exception as screenshot_error:
        raise Exception(f"Failed to capture screenshot: {screenshot_error}")


async def select_typical_mode(page: Page) -> bool:
    try:
        await page.get_by_role("button", name="Live traffic").click()
        await page.wait_for_timeout(sec(1))
        await page.get_by_role("menuitemradio", name="Typical traffic").click()
        await page.wait_for_timeout(sec(1))
        logger.info("Typical traffic mode selected")
        # await page.wait_for_timeout(sec(2))
        return True
    except Exception as err:
        logger.info(f"Failed to select the traffic typical mode: {err}")

    return False


async def select_typical_mode_day(page: Page, day_of_week: str):
    try:
        day_index = DAY_MAP.get(str(day_of_week).strip().lower(), 0)
        await page.evaluate(
            f"""
            const days = document.querySelectorAll('#layer button'); // div div div 
            if (days[{day_index}]) days[{day_index}].click();
            """
        )
        # await page.wait_for_timeout(sec(2))
        logger.info("Successfully selection day for Typical mode")
    except Exception as err:
        logger.warning(f"Failed to select the traffic day of week: {err}")


async def select_typical_mode_time(page: Page, target_time: str):
    try:
        target_time = target_time.strip().upper()
        if re.fullmatch(r"(1[0-2]|[1-9])(?::[0-5]\d)?[AP]M", target_time):
            clean_time = re.sub(r":00(?=[AP]M)", "", target_time)
            pos = TIME_MAP.get(clean_time, 19)  # default at 9:00 AM

        slider_track = await page.query_selector('div[jsaction="layer.timeClicked"]')
        if slider_track:
            track_box = await slider_track.bounding_box()
            target_x = track_box["x"] + (pos / 100) * track_box["width"]
            await page.mouse.click(target_x, track_box["y"] + track_box["height"] / 2)

        # # Wait for the slider container to be available
        # await page.wait_for_selector(
        #     'div[jsaction="layer.timeClicked"]', timeout=sec(5)
        # )

        # # Get the slider element using the more specific selector
        # slider = await page.query_selector(
        #     'div[jsaction="layer.timeClicked"] span[role="slider"]'
        # )

        # if not slider:
        #     # Alternative selector if the first one doesn't work
        #     slider = await page.query_selector('span.BG6pXb[role="slider"]')

        # # Get the slider track (parent container) to calculate relative positions
        # slider_track = await page.query_selector('div[jsaction="layer.timeClicked"]')
        # track_box = await slider_track.bounding_box()

        # # Calculate the target X position based on percentage
        # # The slider moves within the track width
        # track_width = track_box["width"]
        # target_x = track_box["x"] + (pos / 100) * track_width

        # # Click on the target position on the slider track
        # await page.mouse.click(target_x, track_box["y"] + track_box["height"] / 2)

        # await page.wait_for_timeout(sec(2))
        logger.info("Successfully selection time for Typical mode")
    except Exception as err:
        logger.warning(f"Failed to adjust the traffic time: {err}")


async def cleaning_up_unimportant_elements(page: Page):
    try:
        await page.evaluate(
            # """
            # const elementsToRemove = [
            #     document.getElementById('assistive-chips'),
            #     document.getElementById('omnibox-container'),
            #     document.getElementById('vasquette'),
            #     document.querySelector("#QA0Szd > div > div"),
            #     document.querySelector("#content-container > div.app-viewcard-strip.ZiieLd > div.app-bottom-content-anchor.HdXONd > div.app-vertical-widget-holder.Hk4XGb"),
            #     document.querySelector("#content-container > div.app-viewcard-strip.ZiieLd > div.app-bottom-content-anchor.HdXONd > div.app-horizontal-widget-holder.Hk4XGb"),
            #     document.querySelector("#content-container > div.scene-footer-container.Hk4XGb"),
            #     document.querySelector("#minimap > div > div"),
            #     // document.getElementById('layer') // to remove (traffic type selection dialog)
            # ];
            # elementsToRemove.forEach(el => {
            #     if (el) el.remove();
            # });
            # """
            """
            // Remove only the most obstructive elements
            const selectors = [
                '#assistive-chips',
                '#omnibox-container',
                '#vasquette',
                '.app-viewcard-strip',
                '.scene-footer-container',
                '.XltNde'
            ];
            selectors.forEach(sel => {
                const el = document.querySelector(sel);
                if (el) el.remove();
            });
            """
        )
        logger.info("Successfully cleaned up UI elements")
    except Exception as cleanup_error:
        logger.warning(f"Failed to clean up UI elements: {cleanup_error}")


async def capture_google_maps_screenshot(
    context: BrowserContext,
    lat: float,
    lng: float,
    day_of_week: Optional[Union[str, int]] = None,
    target_time: Optional[str] = None,
) -> tuple[str, bool]:

    live_traffic = True

    try:
        page = await context.new_page()

        map_url = google_map_url(lat, lng)
        await page.goto(map_url, wait_until="domcontentloaded", timeout=sec(10))
        logger.info(f"Loading Google Maps URL: {map_url}")

        # await page.wait_for_timeout(sec(10))

        # Position the mouse in the center of the map first
        await page.mouse.move(
            page.viewport_size.get("width", 600) // 2,
            page.viewport_size.get("height", 400) // 2,
        )
        # Zoom operations to trigger data refresh
        for i in range(3):
            await page.mouse.wheel(0, 100 * (-1 if i == 0 else 1))
            await page.wait_for_timeout(500)

        # Select traffic type (typical or live)
        try:
            if day_of_week is not None or target_time is not None:
                await page.wait_for_timeout(sec(5))
                if await select_typical_mode(page):
                    # await page.wait_for_timeout(sec(10))

                    if day_of_week is not None:
                        await select_typical_mode_day(page, day_of_week)
                        # await page.wait_for_timeout(sec(10))

                    if target_time is not None:
                        await select_typical_mode_time(page, target_time)
                        # await page.wait_for_timeout(sec(10))

                    live_traffic = False
        except Exception as traffic_error:
            logger.info(f"Using live traffic mode: {traffic_error}")

        await cleaning_up_unimportant_elements(page)

        screenshot_path = await save_traffic_screenshot(
            page, lat, lng, day_of_week, target_time
        )

        return screenshot_path, live_traffic
    except Exception as err:
        logger.error(f"Failed to capture Google Maps screenshot at {lat}, {lng}: {err}")
    finally:
        await page.close()


async def analyze_location_traffic(
    context: BrowserContext,
    lat: float,
    lng: float,
    day_of_week: Optional[Union[str, int]] = None,
    target_time: Optional[str] = None,
    storefront_direction: str = "north",  # Reintroduced parameter
    *,
    save_to_static: bool = False,
    request_base_url: str = None,
):
    if not context:
        error_msg = f"Failed to setup Browser for location ({lat}, {lng})."
        logger.error(error_msg)
        raise Exception(error_msg)

    try:
        # Capture screenshot
        screenshot_path, live_traffic = await capture_google_maps_screenshot(
            context,
            lat,
            lng,
            day_of_week=day_of_week,
            target_time=target_time,
        )

        if not screenshot_path:
            error_msg = f"Failed to capture screenshot for location ({lat}, {lng}). Check Google Maps accessibility and browser automation."
            logger.error(error_msg)
            raise Exception(error_msg)

        # Add pin to image for verification, passing storefront_direction
        pinned_screenshot_path = add_pin_to_image(screenshot_path, storefront_direction)

        # Analyze traffic in the image, passing storefront_direction
        analysis = analyze_traffic_in_image(
            pinned_screenshot_path, lat, lng, storefront_direction
        )

        if not analysis:
            error_msg = f"Failed to analyze traffic in screenshot for location ({lat}, {lng}). Image analysis returned no results."
            logger.error(error_msg)
            raise Exception(error_msg)

        # Calculate final score
        result = calculate_final_traffic_score(analysis)

        # Cleanup original screenshot
        if (
            os.path.exists(screenshot_path)
            and screenshot_path != pinned_screenshot_path
        ):
            os.remove(screenshot_path)

        # Handle static file saving if requested
        if save_to_static:
            static_filename = os.path.basename(pinned_screenshot_path)
            static_path = os.path.join(TRAFFIC_SCREENSHOTS_STATIC_PATH, static_filename)

            shutil.copy2(pinned_screenshot_path, static_path)
            result["screenshot_path"] = static_path

            # Generate screenshot URL if base_url is provided
            if request_base_url:
                try:
                    # Convert to string to handle URL objects
                    base_url_str = str(request_base_url).rstrip("/")

                    static_root = os.path.dirname(
                        os.path.dirname(TRAFFIC_SCREENSHOTS_STATIC_PATH)
                    )
                    rel_path = os.path.relpath(static_path, static_root)
                    screenshot_url = (
                        f"{base_url_str}/static/{rel_path.replace(os.sep, '/')}"
                    )

                    result["screenshot_url"] = screenshot_url
                    logger.info(f"Generated screenshot URL: {screenshot_url}")
                except Exception as e:
                    logger.warning(f"Failed to generate screenshot URL: {e}")
        else:
            result["screenshot_path"] = pinned_screenshot_path

        # Add metadata
        result.update(
            {
                "method": "google_maps_screenshot",
                "coordinates": {"lat": lat, "lng": lng},
                "analysis_timestamp": time.time(),
                "storefront_details": analysis.get("storefront_details", {}),
                "traffic_type": "live" if live_traffic else "typical",
            }
        )

        logger.info(
            f"Google Maps traffic analysis completed for {lat}, {lng}: Score {result['score']}"
        )
        return result

    except Exception as err:
        error_msg = f"Google Maps traffic analysis failed for location ({lat}, {lng}): {str(err)}"
        logger.error(error_msg)
        raise Exception(error_msg) from err


async def accept_cookies(page: Page) -> bool:
    """Accept cookies if present"""
    try:
        # Try multiple possible cookie button selectors
        selectors = (
            # 'button:has-text("Accept all")',
            # 'button:has-text("I agree")',
            # 'button:has-text("Accept")',
            # '[aria-label*="Accept"], [aria-label*="accept"]',
            "Accept all",
            "I agree",
            "Accept",
        )

        for selector in selectors:
            try:
                await page.get_by_role("button", name=selector).click(timeout=sec(5))
                await page.wait_for_timeout(sec(5))
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False


async def setup_context_with_cookies(browser: BrowserContext) -> BrowserContext:
    """Setup context and accept cookies once for all pages"""

    context = await browser.new_context(
        locale="en-US",
        viewport=ViewportSize(width=1200, height=800),
        user_agent=USER_AGENT,
    )

    try:
        # Create a temporary page to accept cookies once for this context
        setup_page = await context.new_page()
        await setup_page.goto(
            google_map_url(0, 0, zoom=0), wait_until="domcontentloaded", timeout=sec(10)
        )
        await accept_cookies(setup_page)
        logger.info("Cookie banner accepted")
    except Exception:
        logger.info("No cookie banner found")
    finally:
        await setup_page.close()

    return context
