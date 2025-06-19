# DriveBC.ca-Images
Image Ingestion Service for DriveBC.ca

The DriveBC Image Ingestion Service is composed of several [Docker](https://www.docker.com/) containers:
[FastAPI](https://fastapi.tiangolo.com/) backend, [FTP](https://en.wikipedia.org/wiki/File_Transfer_Protocol) served as a testing FTP server and two consumers container for testing.

- [Quickstart](#quickstart)
- [Environment configuration](#environment-configuration)

## <a name="quickstart"></a>Quickstart
1. Clone or download the project from: (https://github.com/bcgov/DriveBC.ca-Images.git)
2. Setup [environment variables](#environment-configuration)
3. Run docker-compose, 'cd DriveBC.ca-Images/src/image_ingestion_service && docker-compose up -d --build'
4. The following should be reachable:
   - image-receiver-drivebc-image: backend API endpoint for receiving images at http://localhost:8000/api/images/
   - ftp-server-drivebc-image: FTP server for testing
   - consumer-drivebc-image: test consumer for consuming received images from RabbitMQ once images received
   - consumer-drivebc-drivebc-image: another test consumer for consuming received images from RabbitMQ once images received

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

3. Image Processing Consumers
- Two separate services consume the images from RabbitMQ:
   - consumer – likely performs general processing or analysis
   - consumer-drivebc – likely handles DriveBC-specific logic, ie. watermark
- Each consumer independently picks up and processes images from the queue based on its logic or configuration.

## Test

Port forward RabbitMQ to local:
- Login in to OpenShift silver with oc cli command.
- Change project to RabbitMQ Dev namespace: oc project f73c1f-dev 
- Port forward RabbitMQ 5672 port to local host all interfaces: kubectl port-forward svc/moti-rabbitmq 5672:5672 --address 0.0.0.0. (oc command does not work to port forward to all interfaces.)

Run curl from Windows Command Prompt:
- curl -X POST -H "camera-id: cam123" -H "username: north_user" -H "password: north_pass"  -F "image=@C:/work/DriveBC.ca-Images/src/image_ingestion_service/image/cam123.jpg" http://localhost:8000/images
- Ensure the camera-id header and correct file path are used. Replace credentials as needed for authentication testing.

Verify Image Reception in Consumers:
Check the following Docker containers to confirm that the image has been consumed from RabbitMQ:
- consumer-drivebc-image
- consumer-drivebc-drivebc-image
- Look for log entries indicating the image file received.
- Look for metrics at http://localhost:8000/api/metrics


Test Basic Authentication Behavior:
- Use valid credentials to confirm a successful auth.
- Use invalid credentials to verify that the endpoint rejects unauthorized requests.

Test incorrect image format or file:
- Replace the image with a .txt file or a .png file to verify the image-receiver container has a correct response.