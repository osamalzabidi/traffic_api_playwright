#!/usr/bin/python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime, timedelta
from typing import Any

import requests

API_URL = "http://157.180.121.131:8000"
USERNAME = "admin"
PASSWORD = "123456"


# Load all locations from JSON file
def load_locations_from_file(filename="locations.json") -> list[dict[str, Any]]:
    """Load locations from JSON file"""
    try:
        with open(filename, "r") as f:
            locations = json.load(f)

        print(f"✅ Loaded {len(locations)} locations from {filename}")
        return locations
    except FileNotFoundError:
        print(f"❌ Error: {filename} not found")
        return []
    except json.JSONDecodeError:
        print(f"❌ Error: Invalid JSON in {filename}")
        return []


def login() -> str:
    """Authenticate and return JWT token"""

    url = f"{API_URL}/login"
    data = {"username": USERNAME, "password": PASSWORD}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    res = requests.post(url, data=data, headers=headers)
    if res.status_code != 200:
        raise Exception(f"Login failed: {res.text}")

    token = res.json()["access_token"]
    print(f"✅ Logged in successfully. Token: {token[:20]}...")
    return token


def submit_batch(
    token: str, locations: list[dict[str, Any]], batch_number: int, total_batches: int
) -> dict[str, Any]:
    """Submit a batch of locations"""

    url = f"{API_URL}/process-locations"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    start_time = datetime.now()
    print(
        f"⏱️  Batch {batch_number}/{total_batches} started at {start_time.strftime('%H:%M:%S')}"
    )

    res = requests.post(
        url,
        json={"save_to_static": True, "locations": locations},
        headers=headers,
        timeout=(5, 150),
    )
    if res.status_code != 200:
        raise Exception(f"Batch submission failed: {res.text}")

    result = res.json()

    completed = result.get("completed", 0)
    total = result.get("locations_count", len(result.get("result", {})))
    print(f"⏱️  Batch {batch_number}/{total_batches}, {completed}/{total} done")

    end_time = datetime.now()
    duration = end_time - start_time
    total_seconds = int(duration.total_seconds())
    duration_str = str(timedelta(seconds=total_seconds))

    failure_count = (
        sum([1 for t in result.get("result", []) if t.get("traffic_type") == "live"])
        if result.get("result")
        else 0
    )

    print(
        f"\n🏁 Batch {batch_number}/{total_batches} finished at {end_time.strftime('%H:%M:%S')}"
    )
    print(f"⏰ Batch time: {duration_str}")
    print(
        "✅ Batch complete!"
        if not result.get("error")
        else f"⚠️ Batch ended: {result.get('error')}"
    )
    if total > 0:
        print(
            f"📊 Failure percentage: {((total - completed) + failure_count) / total * 100:.2f}%"
        )
    return result


def process_all_locations_in_batches(
    token: str, locations: list[dict[str, Any]], batch_size=20
):
    """Process all locations in batches and combine results"""

    total_locations = len(locations)
    batches = [
        locations[i : i + batch_size] for i in range(0, total_locations, batch_size)
    ]
    total_batches = len(batches)

    print(
        f"\n📦 Processing {total_locations} locations in {total_batches} batches of {batch_size}"
    )

    all_results = {
        "overall_status": "processing",
        "total_locations": total_locations,
        "total_batches": total_batches,
        "batch_size": batch_size,
        "start_time": datetime.now().isoformat(),
        "batches": [],
    }

    successful_batches = 0
    failed_batches = 0

    for i, batch_locations in enumerate(batches, 1):
        print(f"\n{'='*50}")
        print(
            f"🔄 Processing Batch {i}/{total_batches} ({len(batch_locations)} locations)"
        )
        print(f"{'='*50}")

        try:
            batch_result = submit_batch(token, batch_locations, i, total_batches)
            # batch_result = poll_job(token, job_id, i, total_batches)

            if batch_result:
                batch_info = {
                    "batch_number": i,
                    "request_id": batch_result.get("request_id"),
                    # "status": batch_result.get("status"),
                    "submitted_locations": len(batch_locations),
                    "completed_locations": batch_result.get("completed", 0),
                    "result": batch_result.get("result", {}),
                    "processing_time": (
                        datetime.now()
                        - datetime.fromisoformat(all_results["start_time"])
                    ).total_seconds(),
                }
                all_results["batches"].append(batch_info)

                if not batch_result.get("error"):
                    successful_batches += 1
                else:
                    failed_batches += 1
            else:
                failed_batches += 1
                all_results["batches"].append(
                    {
                        "batch_number": i,
                        "status": "failed",
                        "error": batch_result.get("error"),
                    }
                )

        except Exception as e:
            print(f"❌ Error processing batch {i}: {e}")
            failed_batches += 1
            all_results["batches"].append(
                {"batch_number": i, "status": "failed", "error": str(e)}
            )

    # Update overall status
    all_results["end_time"] = datetime.now().isoformat()
    total_duration = datetime.fromisoformat(
        all_results["end_time"]
    ) - datetime.fromisoformat(all_results["start_time"])
    all_results["total_processing_time_seconds"] = total_duration.total_seconds()

    if failed_batches == 0:
        all_results["overall_status"] = "completed_successfully"
    elif successful_batches == 0:
        all_results["overall_status"] = "all_failed"
    else:
        all_results["overall_status"] = "completed_with_errors"

    all_results["successful_batches"] = successful_batches
    all_results["failed_batches"] = failed_batches

    # Calculate overall statistics
    total_completed_locations = sum(
        batch.get("completed_locations", 0) for batch in all_results["batches"]
    )
    all_results["total_completed_locations"] = total_completed_locations
    all_results["completion_rate"] = (
        f"{(total_completed_locations / total_locations) * 100:.2f}%"
    )

    return all_results


def save_combined_results(results, filename_prefix="traffic_analysis") -> str:
    """Save combined results to a JSON file"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # filename = f"{filename_prefix}_combined_{timestamp}.json"
    filename = f"{filename_prefix}_combined.json"

    with open(filename, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n💾 Combined results saved to: {filename}")
    return filename


if __name__ == "__main__":
    print("=== 🧪 Batch Processing 100 Locations from JSON File ===")

    # Load all locations from JSON file
    all_locations = load_locations_from_file("locations.json")

    if not all_locations:
        print("❌ No locations to process. Exiting.")
        exit(1)

    # Authenticate
    token = login()

    # Process all locations in batches
    combined_results = process_all_locations_in_batches(
        token, all_locations, batch_size=20
    )

    # Save combined results
    output_file = save_combined_results(combined_results, "playwright")

    # Print summary
    print(f"\n{'='*60}")
    print("📊 PROCESSING SUMMARY")
    print(f"{'='*60}")
    print(f"📍 Total locations processed: {combined_results['total_locations']}")
    print(f"📦 Total batches: {combined_results['total_batches']}")
    print(f"✅ Successful batches: {combined_results['successful_batches']}")
    print(f"❌ Failed batches: {combined_results['failed_batches']}")
    print(f"🏁 Overall status: {combined_results['overall_status']}")
    print(f"📈 Completion rate: {combined_results['completion_rate']}")
    print(
        f"⏰ Total processing time: {combined_results['total_processing_time_seconds']:.2f} seconds"
    )
    print(f"💾 Results saved to: {output_file}")
