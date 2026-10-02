# DriveBC.ca-Images
Image Ingestion Service for DriveBC.ca

The DriveBC Image Ingestion Service is composed of a single [Docker](https://www.docker.com/) container running a FastAPI backend. It integrates with a RabbitMQ message broker, and a RabbitMQ consumer for processing ingested images.

- [Quickstart](#quickstart)
- [Environment configuration](#environment-configuration)

## <a name="quickstart"></a>Quickstart
1. Clone or download the project from: (https://github.com/bcgov/DriveBC.ca-Images.git)
2. Setup [environment variables](#environment-configuration)
3. Follow [Run locally with Podman Compose](#run-locally-with-podman-compose) to start the receiver and a local RabbitMQ broker.
4. The following should be reachable:
   - image-receiver: backend API endpoint for receiving images at http://localhost:8000/api/images/

## <a name="environment-configuration"></a>Environment configuration
Environments are configured via environment variables passed to Docker Compose in a .env file.
Copy and rename ".env.example" into ".env" in the same directory and replace values according to your target environment.

## Run locally with Podman Compose

Install Podman and start its machine (on Windows or macOS):

```powershell
podman machine start
```

From the repository root, copy the example environment file. Its RabbitMQ
settings point to the local broker in the Compose file. The example camera
credentials are for local development only; replace them as needed. Leave the
database fields blank only if you just want to start the service and check its
health endpoint; camera authentication backed by the database will not work
without valid database settings.

```powershell
Copy-Item src\image_ingestion_service\.env.example src\image_ingestion_service\.env
podman compose --env-file src\image_ingestion_service\.env -f src\image_ingestion_service\docker-compose.yml up --build -d
```

The Compose file builds the receiver from the repository root and starts a
local RabbitMQ broker. Check the API, logs, or RabbitMQ management page:

```powershell
Invoke-RestMethod http://localhost:8000/api/healthz
podman compose --env-file src\image_ingestion_service\.env -f src\image_ingestion_service\docker-compose.yml logs -f
```

- Receiver API: <http://localhost:8000>
- RabbitMQ management UI: <http://localhost:15672> (credentials from `.env`)

Stop the local services when finished:

```powershell
podman compose --env-file src\image_ingestion_service\.env -f src\image_ingestion_service\docker-compose.yml down
```

On Linux or macOS, use `cp` instead of `Copy-Item`; the `podman compose`
commands are otherwise the same, with `/` path separators.

## Image ingestion Workflow

Axis Camera Image Ingestion Workflow

1. Camera Configuration
- The end user configures an Axis camera to upload images via HTTP or HTTPS to a specific endpoint.
- This endpoint accepts POST request for receiving images and passthrough the image to MOTT RabbitMQ.

2. Image Receiver Service
- Basic Authentication: Verifies that the request has valid camera id, ip address and credentials.
- If all checks pass, the Image Receiver service will passthrough the images to RabbitMQ.
- If either check fails, the request is denied and logged.
- It exposes three endpoints:
   - GET /health – for health checks
   - POST /images – for receiving image uploads
   - GET /metrics – for Prometheus metrics (e.g., success/failure counters)

3. Image Processing Consumer (Implemented in DriveBC)
- A separate service to consume the images from RabbitMQ:
   - consumer – performs general processing or analysis to handles DriveBC-specific logic, ie. watermark, saving images

## Test

Port forward MOTT RabbitMQ to local:
- Login in to OpenShift silver with oc cli command.
- Change project to RabbitMQ Dev namespace: oc project f73c1f-dev 
- Port forward RabbitMQ 5672 port to local host all interfaces: kubectl port-forward svc/moti-rabbitmq 5672:5672 --address 0.0.0.0. (oc command does not work to port forward to all interfaces.)

Run curl from Windows Command Prompt:
- curl -X POST -H "camera-id: cam123" -H "username: north_user" -H "password: north_pass"  -F "image=@C:/work/DriveBC.ca-Images/src/image_ingestion_service/image/cam123.jpg" http://localhost:8000/images
- Ensure the camera-id header and correct file path are used. Replace credentials as needed for authentication testing.

Verify Image Reception in RabbitMQ:
To confirm that images are being successfully consumed from RabbitMQ, follow these steps:

Check the RabbitMQ Dev Console
- Access the RabbitMQ Dev management interface: https://dev-moti-rabbitmq.apps.silver.devops.gov.bc.ca/#/

Verify the Queue Binding
- Ensure that the appropriate queue is created and correctly bound to the exchange.
- Confirm that image messages are passing through the queue.

Look for log entries confirming receipt of each image.
- Monitor Application Metrics
- Visit http://localhost:8000/api/metrics to view application-level metrics and confirm ingestion activity.

Test Basic Authentication Behavior:
- Use valid credentials to confirm a successful auth.
- Use invalid credentials to verify that the endpoint rejects unauthorized requests.

Test incorrect image format or file:
- Replace the image with a .txt file or a .png file to verify the image-receiver container has a correct response.

## Github Release Process
We use Github Actions with Helm to deploy updates to the three environments, dev, uat and prod. Here is how it works for each.

### Dev
You have two options
1. Any push to main will automatically trigger a deployment to dev
1. You can manually trigger a deployment by going to the action, `Run workflow` and then selecting the branch you want to build and push to the dev environment

### UAT
This one is manually triggered. Go to the `2. Build & Deploy to UAT` then `Run workflow`. Once you do that it will automatically create a `rc` tag that auto increments. It then deploys that to the UAT environment in OpenShift for testing.

### Prod
This workflow is triggered through the 'Releases' section of Github action.
1. Go to releases: https://github.com/bcgov/DriveBC.ca-Images/releases
1. Click `Draft a new release`
1. Select the tag you want to release
1. Give the release a title (ie `0.0.1`)
1. Click `Generate release notes` if you like
1. Click `Publish release` which will automatically trigger the workflow to deploy that tag you selected to prod.

# Running Unit Tests

This project uses **pytest** for unit testing.

## Prerequisites

Ensure the following packages are installed:

- pytest
- pytest-mock
- pytest-asyncio
- pytest-cov
- httpx2

These dependencies should be included in `requirements-dev.txt`.

## Updating Python Dependencies

Edit `requirements.in` for application dependencies or `requirements-dev.in` for
development and test dependencies. The dev input includes `requirements.txt`,
so compile the base requirements first whenever `requirements.in` changes.
Dependency updates are managed by Renovate, configured in `renovate.json`.

From the repository root, in PowerShell:

```powershell
Set-Location src\image_ingestion_service\image_receiver
py -3 -m venv .venv  # Run once if the virtual environment does not exist
.\.venv\Scripts\python.exe -m pip install --upgrade pip pip-tools
.\.venv\Scripts\pip-compile.exe --generate-hashes --output-file=requirements.txt requirements.in
.\.venv\Scripts\pip-compile.exe --generate-hashes --output-file=requirements-dev.txt requirements-dev.in
```

On Linux or macOS, run the equivalent commands from the receiver directory:

```bash
python3 -m venv .venv  # Run once if the virtual environment does not exist
.venv/bin/python -m pip install --upgrade pip pip-tools
.venv/bin/pip-compile --generate-hashes --output-file=requirements.txt requirements.in
.venv/bin/pip-compile --generate-hashes --output-file=requirements-dev.txt requirements-dev.in
```

If you only changed `requirements-dev.in`, you only need to recompile
`requirements-dev.txt`. If you changed `requirements.in`, recompile
`requirements.txt` first, then `requirements-dev.txt`. Review both generated
files and commit them together with the input-file change.

To verify the generated dev requirements and run the tests in the virtual
environment:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -v
```

Use `python -m pip install --require-hashes -r requirements-dev.txt` and
`python -m pytest -v` on Linux or macOS.

## Run All Tests

Run from `src/image_ingestion_service/image_receiver` after installing the
development requirements as described above:

```bash
python -m pytest
```

or with verbose output:

```bash
python -m pytest -v
```

or

```bash
python -m pytest -s -vv
```

## Run a Specific Test File

```bash
python -m pytest tests/test_main.py
```

Example:

```bash
python -m pytest tests/test_auth.py
```

## Run a Single Test

```bash
python -m pytest tests/test_main.py::test_upload_success
```

## Generate a Coverage Report

The coverage plugin is included in `requirements-dev.txt`. Run this from the
receiver directory:

```bash
python -m pytest --cov=app --cov-report=term-missing
```

GitHub Actions publishes coverage in the workflow run summary and uploads the
Cobertura report to GitHub Code Quality, where coverage is displayed on pull
requests. Uploads are skipped for pull requests from forks because they cannot
write coverage data to the base repository.

## Test Structure

```
tests/
├── conftest.py          # Shared fixtures and authentication overrides
├── test_main.py         # API endpoint tests
├── test_auth.py         # Authentication unit tests
├── test_db.py           # Database access tests
└── test_rabbitmq.py     # RabbitMQ publisher tests
```

## Notes

- Tests use mocked dependencies and do not require a running RabbitMQ instance.
- Database interactions are mocked and do not require a SQL Server instance.
- Authentication is overridden in `conftest.py` for API endpoint tests.
- Always run tests using:

```bash
python -m pytest
```

instead of

```bash
pytest
```

to ensure the correct Python environment is used.
