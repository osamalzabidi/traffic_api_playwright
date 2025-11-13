# Google Maps Traffic Analyzer API

A FastAPI-based service that analyzes Google Maps traffic data for specific locations using browser automation and computer vision.

## Features

- **Traffic Analysis**: Analyze traffic conditions around specific coordinates
- **Historical Data**: Get typical traffic patterns for specific days and times
- **Storefront Orientation**: Consider storefront direction in traffic analysis
- **Batch Processing**: Process multiple locations in parallel
- **RESTful API**: Fully documented API endpoints
- **Authentication**: JWT-based authentication system
- **Rate Limiting**: Configurable rate limiting for API endpoints
- **Database Storage**: SQLite database for storing analysis results
- **Docker Support**: Containerized deployment with Docker
- **Health Monitoring**: Comprehensive health check endpoints

## Architecture

The application consists of several key components:

1. **FastAPI Server** - Main API server with endpoints for traffic analysis
2. **Playwright Automation** - Browser automation for capturing Google Maps screenshots
3. **Image Processing** - Computer vision algorithms for analyzing traffic colors
4. **Authentication** - JWT-based user authentication
5. **Database** - SQLite database for storing users, jobs, and analysis results

## Installation

### Prerequisites

- Python 3.8+
- Playwright browsers
- SQLite

### Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd traffic-analyzer
   ```
2. **Install dependencies**
    ```bash
    pip install -r requirements.txt
    playwright install chromium
    ```

3. **Set environment variables**
    ```bash
    export JWT_SECRET="your-secret-key"
    export ADMIN_PASSWORD="admin123"
    export RATE_LIMIT="10/minute"
    ```

4. **Run the application**
    ```bash
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```

### Docker Deployment

1. **Build and run with Docker Compose**
    ```bash
    docker-compose up --build
    ```

2. **Set environment variables in `.env` file**
    ```bash
    JWT_SECRET=your-secret-key
    ADMIN_PASSWORD=admin123
    RATE_LIMIT=10/minute
    PLAYWRIGHT_PROXY_SERVER=your-proxy-server
    PLAYWRIGHT_PROXY_USERNAME=your-proxy-username
    PLAYWRIGHT_PROXY_PASSWORD=your-proxy-password
    ```

## API Documentation

Once running, access the API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Health Endpoints

The API provides comprehensive health monitoring endpoints:

**`GET /health`**

Comprehensive health check that verifies all system dependencies:

- Database connectivity
- Browser automation status
- File system permissions

**Response:**
```json
{
  "status": "healthy",
  "timestamp": 1234567890.123,
  "version": "1.0.0",
  "dependencies": {
    "database": {
      "status": "healthy",
      "details": "Database connection successful"
    },
    "browser_automation": {
      "status": "healthy",
      "details": "Playwright browser context is available"
    },
    "file_system": {
      "status": "healthy",
      "details": "File system permissions are OK"
    }
  }
}
```

**`GET /health/ready`**

Readiness probe for Kubernetes/container orchestration. Checks if the service is ready to accept traffic by verifying critical dependencies.

**Response:**
```json
{
  "status": "ready",
  "timestamp": 1234567890.123
}
```

**`GET /health/live`**

Liveness probe for Kubernetes/container orchestration. Simple check to verify the service is alive and responsive.

**Response:**
```json
{
  "status": "alive",
  "timestamp": 1234567890.123
}
```

### Authentication

The API uses JWT authentication. First, obtain a token:

```bash
curl -X POST "http://localhost:8000/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=123456"
```

### Traffic Analysis Endpoints

**Single Location Analysis**
```bash
curl -X POST "http://localhost:8000/process-location" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "save_to_static": false,
    "save_to_db": false,
    "location": {
      "lat": 24.7136,
      "lng": 46.6753,
      "storefront_direction": "north",
      "day": "Monday",
      "time": "10PM"
    }'
  }
```

**Multiple Locations Analysis**
```bash
curl -X POST "http://localhost:8000/process-locations" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "save_to_static": true,
    "save_to_db": true,
    "locations": [
      {
        "lat": 24.7136,
        "lng": 46.6753,
        "storefront_direction": "north",
        "day": "Monday",
        "time": "10PM"
      },
      {
        "lat": 24.7236,
        "lng": 46.6853,
        "storefront_direction": "south",
        "day": "Tuesday",
        "time": "8:30AM"
      }
    ]
  }'
```
