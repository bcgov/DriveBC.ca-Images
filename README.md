# DriveBC.ca-Images
Image Ingestion Service for DriveBC.ca

The DriveBC Image Ingestion Service is composed of several [Docker](https://www.docker.com/) containers:
[FastAPI](https://fastapi.tiangolo.com/) backend, [nginx](https://nginx.org/) served as a reverse proxy server, [RabbitMQ](https://www.rabbitmq.com/) served as a test RabbitMQ messaging and streaming broker, and [FTP](https://en.wikipedia.org/wiki/File_Transfer_Protocol) served as a testing FTP server.

- [Quickstart](#quickstart)
- [Environment configuration](#environment-configuration)


## <a name="quickstart"></a>Quickstart
1. Install [Docker Desktop](https://docs.docker.com/compose/install/) for your OS[**](#first-asterisk)
2. Clone or download the project from: (https://github.com/bcgov/DriveBC.ca-Images.git)
3. Setup [environment variables](#environment-configuration)
4. Run docker-compose, 'cd DriveBC.ca-Images/src/image_ingestion_service && docker-compose up -d --build'
5. The following should be reachable:
   - nginx-drivebc-image: nginx reverse proxy server for basic auth and ip filtering at http://localhost:80/cgi-bin/notify.cgi
   - image-receiver-drivebc-image: backend API endpoint for receiving images at http://localhost:8000/upload/
   - passthrough-service-drivebc-image: backend API endpoint for pass through images to RabbitMQ and legacy FTP server at http://localhost:8001/forward/
   - rabbitmq-drivebc-image: RabbitMQ container for testing
   - ftp-server-drivebc-image: FTP server for testing
   - consumer-drivebc-image: test consumer for consuming received images from RabbitMQ once images received
   - consumer-drivebc-image: another test consumer for consuming received images from RabbitMQ once images received

<a name="first-asterisk"></a>** You will need to install or update to WSL 2 on Windows (wsl --install or wsl --update)

## <a name="environment-configuration"></a>Environment configuration
Environments are configured via environment variables passed to Docker Compose in a .env file.
Copy and rename ".env.example" into ".env" in the same directory and replace values according to your target environment.

## Test

Run curl from Windows Command Prompt:
- curl -X POST -H "camera-id: CAM001" -F "image=@C:/test/image/1.jpg" http://localhost:8080/cgi-bin/notify.cgi -u bruce:bruce
- Ensure the camera-id header and correct file path are used. Replace credentials as needed for authentication testing.

Verify Image Reception in Consumers:
Check the following Docker containers to confirm that the image has been consumed from RabbitMQ:
- consumer-drivebc-image
- consumer-drivebc-drivebc-image
- Look for log entries indicating the image file received.

IP Whitelist Configuration:
- Ensure the client IP (e.g., 172.20.0.1) is explicitly allowed in the file:
- src/nginx/ip_whitelist.conf
- If the IP is not listed, NGINX will block the request before it reaches the backend. Add the required client ip in the file then restart nginx container.

Test Basic Authentication Behavior:
- Use valid credentials (e.g., bruce:bruce) to confirm a successful auth.
- Use invalid credentials (e.g., wrong password or username) to verify that NGINX correctly rejects unauthorized requests.

Test incorrect image format or file:
- Replace the image with a .txt file or a .png file to verify the image-receiver container has a correct response.

