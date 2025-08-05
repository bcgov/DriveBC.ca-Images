# DriveBC.ca-Images
Image Ingestion Service for DriveBC.ca

The DriveBC Image Ingestion Service is composed of a single [Docker](https://www.docker.com/) container running a FastAPI backend. It integrates with a RabbitMQ message broker, an FTP server for pushing images to legacy systems, and a RabbitMQ consumer for processing ingested images.

- [Quickstart](#quickstart)
- [Environment configuration](#environment-configuration)

## <a name="quickstart"></a>Quickstart
1. Clone or download the project from: (https://github.com/bcgov/DriveBC.ca-Images.git)
2. Setup [environment variables](#environment-configuration)
3. Run docker-compose, 'cd DriveBC.ca-Images/src/image_ingestion_service && docker-compose up -d --build'
4. The following should be reachable:
   - image-receiver: backend API endpoint for receiving images at http://localhost:8000/api/images/

<a name="first-asterisk"></a>** You will need to install or update to WSL 2 on Windows (wsl --install or wsl --update)

## <a name="environment-configuration"></a>Environment configuration
Environments are configured via environment variables passed to Docker Compose in a .env file.
Copy and rename ".env.example" into ".env" in the same directory and replace values according to your target environment.

## Image ingestion Workflow

Axis Camera Image Ingestion Workflow

1. Camera Configuration
- The end user configures an Axis camera to upload images via HTTP or HTTPS to a specific endpoint.
- This endpoint accepts POST request for receiving images and passthrough the image to MOTT RabbitMQ and legacy FTP server.

2. Image Receiver Service
- Basic Authentication: Verifies that the request has valid camera id, ip address and credentials.
- If all checks pass, the Image Receiver service will passthrough the images to RabbitMQ and FTP server.
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

Verify Image Reception in RabbitMQ and legacy FTP server:
To confirm that images are being successfully consumed from RabbitMQ and delivered to the legacy FTP server, follow these steps:

Check the RabbitMQ Dev Console
- Access the RabbitMQ Dev management interface: https://dev-moti-rabbitmq.apps.silver.devops.gov.bc.ca/#/

Verify the Queue Binding
- Ensure that the appropriate queue is created and correctly bound to the exchange.
- Confirm that image messages are passing through the queue.

Check the Legacy FTP Server
- Verify that the image files have been received by the FTP server.

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