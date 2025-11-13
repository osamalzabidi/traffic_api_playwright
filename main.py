#!/usr/bin/python3
# -*- coding: utf-8 -*-


import asyncio
import os
import uuid
from asyncio import Semaphore
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from playwright.async_api import ProxySettings, async_playwright
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import md5_hex

from auth import authenticate_user, create_access_token, get_current_user
from config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    PROXY_BYPASS,
    PROXY_PASSWORD,
    PROXY_SERVER,
    PROXY_USERNAME,
    RATE,
    logger,
)
from db import Base, engine, get_db
from models import (
    LocationData,
    LocationRequest,
    LocationResponse,
    MultiLocationRequest,
    MultiLocationResponse,
    Token,
)
from models_db import Job, TrafficLog, User
from playwright_traffic_analysis import (
    TRAFFIC_SCREENSHOTS_PATH,
    TRAFFIC_SCREENSHOTS_STATIC_PATH,
    analyze_location_traffic,
    setup_context_with_cookies,
)

# FastAPI app
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(TRAFFIC_SCREENSHOTS_PATH, exist_ok=True)
    os.makedirs(TRAFFIC_SCREENSHOTS_STATIC_PATH, exist_ok=True)

    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create admin user
    async for db in get_db():
        admin_pw = os.getenv("ADMIN_PASSWORD", "123456").strip()
        result = await db.execute(select(User).filter_by(username="admin"))
        existing_admin = result.scalar_one_or_none()

        if not existing_admin:
            db.add(User(username="admin", hashed_password=md5_hex(admin_pw)))
            await db.commit()
        break

    # Initialize browser resources
    playwright_instance = None
    browser_instance = None
    browser_context_instance = None

    try:
        playwright_instance = await async_playwright().start()
        proxy_settings = (
            ProxySettings(
                server=PROXY_SERVER,
                bypass=PROXY_BYPASS,
                username=PROXY_USERNAME,
                password=PROXY_PASSWORD,
            )
            if PROXY_SERVER
            else None
        )

        # Launch browser with proper error handling
        browser_instance = await playwright_instance.chromium.launch(
            headless=True,
            chromium_sandbox=False,
            proxy=proxy_settings,
        )

        browser_context_instance = await setup_context_with_cookies(browser_instance)

        # Store resources in app state
        app.state.browser_context = browser_context_instance
        app.state.playwright = playwright_instance
        app.state.browser = browser_instance

        logger.info("✅ Browser resources initialized successfully")

    except Exception as e:
        logger.error(f"❌ Failed to initialize browser: {e}")
        # Clean up partially initialized resources
        if browser_context_instance:
            try:
                await browser_context_instance.close()
            except Exception:
                pass
        if browser_instance:
            try:
                await browser_instance.close()
            except Exception:
                pass
        if playwright_instance:
            try:
                await playwright_instance.stop()
            except Exception:
                pass

        app.state.browser_context = None
        app.state.playwright = None
        app.state.browser = None

    yield

    # Cleanup with proper error handling
    logger.info("🔄 Starting cleanup process...")

    cleanup_errors = []

    # Cleanup browser context
    if hasattr(app.state, "browser_context") and app.state.browser_context:
        try:
            await app.state.browser_context.close()
            logger.info("✅ Browser context closed")
        except Exception as e:
            cleanup_errors.append(f"Browser context: {e}")
            logger.warning(f"⚠️ Failed to close browser context: {e}")

    # Cleanup browser
    if hasattr(app.state, "browser") and app.state.browser:
        try:
            await app.state.browser.close()
            logger.info("✅ Browser closed")
        except Exception as e:
            cleanup_errors.append(f"Browser: {e}")
            logger.warning(f"⚠️ Failed to close browser: {e}")

    # Cleanup playwright
    if hasattr(app.state, "playwright") and app.state.playwright:
        try:
            await app.state.playwright.stop()
            logger.info("✅ Playwright stopped")
        except Exception as e:
            cleanup_errors.append(f"Playwright: {e}")
            logger.warning(f"⚠️ Failed to stop playwright: {e}")

    if cleanup_errors:
        logger.warning(f"❌ Cleanup completed with errors: {cleanup_errors}")
    else:
        logger.info("✅ Cleanup completed successfully")


app = FastAPI(title="Google Maps Traffic Analyzer API", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429, content={"detail": "Too many requests"}
    ),
)

# static directory
os.makedirs("static/images/traffic_screenshots", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Add semaphore to control concurrent browser tabs
CONCURRENT_TABS = 5  # Adjust based on your server capacity


async def process_single_location_with_semaphore(
    semaphore, browser_context, location, base_url, save_to_static
):
    async with semaphore:
        return await process_single_location(
            browser_context, location, base_url, save_to_static
        )


async def process_single_location(
    browser_context, location: LocationData, base_url: str, save_to_static: bool = False
) -> dict[str, Any]:
    traffic_results = await analyze_location_traffic(
        browser_context,
        location.lat,
        location.lng,
        location.day,
        location.time,
        location.storefront_direction,
        save_to_static=save_to_static,
        request_base_url=base_url,
    )
    return {"location": location, "result": traffic_results}


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log the error details
    logger.error(f"Global error: {str(exc)}")

    # Return a generic error response
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "Something went wrong. Please try again later.",
        },
    )


@app.post("/login", response_model=Token)
# @app.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
    user = await authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/process-locations")
# @app.post("/analyze-locations")
@limiter.limit(RATE)
async def process_locations(
    request: Request,
    payload: MultiLocationRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload.locations:
        raise HTTPException(status_code=400, detail="No locations provided")
    if len(payload.locations) > 20:
        raise HTTPException(status_code=400, detail="Max 20 locations per request")

    browser_context = getattr(request.app.state, "browser_context", None)
    if not browser_context:
        raise HTTPException(status_code=503, detail="Browser Context not available")

    try:
        # results = await asyncio.gather(
        #     *(
        #         process_single_location(
        #             browser_context, location, request.base_url, payload.save_to_static
        #         )
        #         for location in payload.locations
        #     ),
        #     return_exceptions=True,
        # )

        semaphore = Semaphore(CONCURRENT_TABS)
        results = await asyncio.gather(
            *(
                process_single_location_with_semaphore(
                    semaphore,
                    browser_context,
                    location,
                    request.base_url,
                    payload.save_to_static,
                )
                for location in payload.locations
            ),
            return_exceptions=True,
        )

        completed_result = [
            r.get("result") for r in results if not isinstance(r, Exception)
        ]
        response = MultiLocationResponse(
            request_id=uuid.uuid4().hex,
            locations_count=len(payload.locations),
            completed=len(completed_result),
            result=completed_result,
            saved_to_db=payload.save_to_db,
            saved_to_static=payload.save_to_static,
            error="\n".join(str(r) for r in results if isinstance(r, Exception)),
        )

        # Save result to DB if requested
        if payload.save_to_db:
            try:
                job = Job(
                    request_id=response.request_id,
                    locations_count=response.locations_count,
                    completed=response.completed,
                    saved_to_static=payload.save_to_static,
                    user_id=user.id,
                )
                db.add(job)

                for res in results:
                    if isinstance(res, Exception):
                        continue

                    log = TrafficLog(
                        lat=res["location"].lat,
                        lng=res["location"].lng,
                        storefront_direction=res["location"].storefront_direction,
                        day=res["location"].day,
                        time=res["location"].time,
                        result=res["result"],
                        job_id=response.request_id,
                    )
                    db.add(log)

                await db.commit()
            except Exception as e:
                logger.warning(
                    f"DB: failed to create process request {response.request_id}: {e}"
                )

        return response
    except Exception as e:
        logger.error(f"Direct processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.get("/fetch-location", response_model=LocationResponse)
# @app.get("/fetch-point", response_model=LocationResponse)
async def get_job(
    request: Request,
    payload: LocationData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    try:
        result = await db.execute(
            select(TrafficLog)
            .join(Job)
            .filter(
                Job.user_id == user.id,
                TrafficLog.lat == payload.lat,
                TrafficLog.lng == payload.lng,
                TrafficLog.storefront_direction == payload.storefront_direction,
                TrafficLog.day == payload.day,
                TrafficLog.time == payload.time,
            )
        )
        saved_to_static = await db.execute(select(Job).filter(Job.user_id == user.id))
        saved_to_static = saved_to_static.scalar_one().saved_to_static
        request_record = result.scalar_one_or_none()
        return LocationResponse(
            request_id=request_record.job_id,
            result=request_record.result,
            saved_to_db=True,
            saved_to_static=saved_to_static,
        )
    except Exception as e:
        logger.warning(
            f"DB: Failed to get request record for {payload.lat}, {payload.lng}: {e}"
        )


@app.post("/process-location", response_model=LocationResponse)
# @app.post("/process-point", response_model=LocationResponse)
@limiter.limit(RATE)
async def get_job(
    request: Request,
    payload: LocationRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    browser_context = getattr(request.app.state, "browser_context", None)
    if not browser_context:
        raise HTTPException(status_code=503, detail="Browser Context not available")

    try:
        result = await process_single_location(
            browser_context, payload.location, request.base_url, payload.save_to_static
        )

        response = LocationResponse(
            request_id=uuid.uuid4().hex,
            result=result["result"],
            saved_to_db=payload.save_to_db,
            saved_to_static=payload.save_to_static,
        )

        # Save result to DB if requested
        if payload.save_to_db:
            try:
                job = Job(
                    request_id=response.request_id,
                    locations_count=1,
                    completed=1,
                    saved_to_static=payload.save_to_static,
                    user_id=user.id,
                )
                db.add(job)

                log = TrafficLog(
                    lat=result["location"].lat,
                    lng=result["location"].lng,
                    storefront_direction=result["location"].storefront_direction,
                    day=result["location"].day,
                    time=result["location"].time,
                    result=result["result"],
                    job_id=response.request_id,
                )
                db.add(log)

                await db.commit()
            except Exception as e:
                logger.warning(
                    f"DB: failed to create process request {response.request_id}: {e}"
                )

        return response
    except Exception as e:
        logger.error(f"Direct processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint to verify the service status and dependencies.
    """
    health_status = {
        "status": "healthy",
        "timestamp": asyncio.get_event_loop().time(),
        "version": "1.0.0",
        "dependencies": {},
    }

    # Check database connection
    try:
        async for db in get_db():
            # Test database connection with a simple query
            result = await db.execute(select(1))
            test_value = result.scalar()
            health_status["dependencies"]["database"] = {
                "status": "healthy",
                "details": "Database connection successful",
            }
            break
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    # Check browser automation status
    browser_context = getattr(app.state, "browser_context", None)
    if browser_context:
        health_status["dependencies"]["browser_automation"] = {
            "status": "healthy",
            "details": "Playwright browser context is available",
        }
    else:
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["browser_automation"] = {
            "status": "unhealthy",
            "error": "Browser context not initialized",
        }

    # Check file system permissions
    try:
        test_dirs = ["static", "static/images", "static/images/traffic_screenshots"]
        for dir_path in test_dirs:
            os.makedirs(dir_path, exist_ok=True)
            test_file = os.path.join(dir_path, "health_test.txt")
            with open(test_file, "w") as f:
                f.write("health_check")
            os.remove(test_file)

        health_status["dependencies"]["file_system"] = {
            "status": "healthy",
            "details": "File system permissions are OK",
        }
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["file_system"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    return health_status


@app.get("/health/ready", tags=["Health"])
async def readiness_probe():
    """
    Readiness probe for Kubernetes/container orchestration.
    Checks if the service is ready to accept traffic.
    """
    readiness_status = {
        "status": "ready",
        "timestamp": asyncio.get_event_loop().time(),
    }

    # Check critical dependencies
    critical_checks = []

    # Database check
    try:
        async for db in get_db():
            await db.execute(select(1))
            critical_checks.append(("database", True))
            break
    except Exception:
        critical_checks.append(("database", False))

    # Browser automation check
    browser_context = getattr(app.state, "browser_context", None)
    critical_checks.append(("browser_automation", bool(browser_context)))

    # Determine overall readiness
    all_ready = all(check[1] for check in critical_checks)
    if not all_ready:
        readiness_status["status"] = "not_ready"
        readiness_status["failed_checks"] = [
            check[0] for check in critical_checks if not check[1]
        ]

    return readiness_status


@app.get("/health/live", tags=["Health"])
async def liveness_probe():
    """
    Liveness probe for Kubernetes/container orchestration.
    Simple check to see if the service is alive.
    """
    return {"status": "alive", "timestamp": asyncio.get_event_loop().time()}


@app.get("/")
async def root():
    return {"message": "Google Maps Parallel Processor API"}


# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000, workers=1, reload=True)
