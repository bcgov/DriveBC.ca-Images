# DriveBC.ca-Images
Image Ingestion Service for DriveBC.ca

The DriveBC Image Ingestion Service is composed of several [Docker](https://www.docker.com/) containers:
[FastAPI](https://fastapi.tiangolo.com/) backend, [nginx](https://nginx.org/) served as a reverse proxy server, and [FTP](https://en.wikipedia.org/wiki/File_Transfer_Protocol) served as a testing FTP server.

- [Quickstart](#quickstart)
- [Environment configuration](#environment-configuration)

## <a name="quickstart"></a>Quickstart
1. Install [Docker Desktop](https://docs.docker.com/compose/install/) for your OS(#first-asterisk)
2. Clone or download the project from: (https://github.com/bcgov/DriveBC.ca-Images.git)
3. Setup [environment variables](#environment-configuration)
4. Run docker-compose, 'cd DriveBC.ca-Images/src/image_ingestion_service && docker-compose up -d --build'
5. The following should be reachable:
   - nginx-drivebc-image: nginx reverse proxy server for basic auth and ip filtering at http://localhost:80/cgi-bin/notify.cgi (Removed)
   - image-receiver-drivebc-image: backend API endpoint for receiving images at http://localhost:8000/images/
   - passthrough-service-drivebc-image: backend API endpoint for pass through images to RabbitMQ and legacy FTP server at http://localhost:8001/forward/ (Removed)
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
- This endpoint is the public facing URL handled by an NGINX reverse proxy.

2. Request Reaches NGINX Reverse Proxy (Removed)
- The image upload request is received by the NGINX reverse proxy server.
- NGINX performs two key security checks:
   - Basic Authentication: Verifies that the request has valid credentials.
   - IP Whitelisting: Ensures the request originates from an approved IP address.

3. NGINX Proxies to Image Receiver (Removed)
- If both checks pass, NGINX forwards the request to the Image Receiver service.
- If either check fails, the request is denied.

4. Image Receiver Service
- The Image Receiver logs the incoming request and handles it appropriately.
- It exposes three endpoints:
   - GET /health – for health checks
   - POST /images – for receiving image uploads
   - GET /metrics – for Prometheus metrics (e.g., success/failure counters)
- Upon receiving a valid image upload, it forwards (passes through) the request to a separate Pass-Through service.

5. Pass-Through Service (Removed)
- The Pass-Through service takes the image from the receiver and performs two actions:
   - Pushes the image to a RabbitMQ message queue (MOTT RabbitMQ)
   - Uploads a copy to a legacy FTP server for backward compatibility

6. Image Processing Consumers
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
- curl -X POST -H "camera-id: cam123" -H "camera-location: North" -H "username: north_user" -H "password: north_pass"  -F "image=@C:/test/image/1.jpg" http://localhost:8000/images
- Ensure the camera-id header and correct file path are used. Replace credentials as needed for authentication testing.

Verify Image Reception in Consumers:
Check the following Docker containers to confirm that the image has been consumed from RabbitMQ:
- consumer-drivebc-image
- consumer-drivebc-drivebc-image
- Look for log entries indicating the image file received.
- Look for metrics at http://localhost:8000/metrics

IP Whitelist Configuration: (Removed)
- Ensure the client IP (e.g., 172.20.0.1) is explicitly allowed in the file:
- src/nginx/ip_whitelist.conf
- If the IP is not listed, NGINX will block the request before it reaches the backend. Add the required client ip in the file then restart nginx container.

Test Basic Authentication Behavior:
- Use valid credentials to confirm a successful auth.
- Use invalid credentials (e.g., wrong password or username) to verify that the endpoint rejects unauthorized requests.

Test incorrect image format or file:
- Replace the image with a .txt file or a .png file to verify the image-receiver container has a correct response.