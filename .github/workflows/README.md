# Github Workflows

### Initial Github Setup

The dev, uat, prod workflows need to have environment variables setup in OpenShift

Add these variables like this:
1. In Github go to Settings
1. Click Environments
1. Click New Environment
1. Give it a name (dev, uat, prod)
1. Add these Environment and Secret Variables
    1. Variable: `OPENSHIFT_NAMESPACE`
        - Use the project namespace with the `-dev` (ie `abc123-dev`)
    1. Variable: `OPENSHIFT_GOLD_SERVER`
        - This will be the API Server you see when you get your token from OpenShift
    1. Secret: `OPENSHIFT_GOLD_TOKEN`
        - Use the Pipeline Token (From `pipeline-token-xxxxxxxx` secret)
    1. Variable: `OPENSHIFT_GOLDDR_SERVER`
        - This will be the API Server you see when you get your token from OpenShift
    1. Secret: `OPENSHIFT_GOLDDR_TOKEN`
        - Use the Pipeline Token (From `pipeline-token-xxxxxxxx` secret)


# Workflows
### 1. Build & Deploy to Dev
- **What:** Generates a new image from the code in `main` and deploys to Gold/GoldDR
- **Trigger:** Manual or on push to `main` branch
- **Image Tags:** `latest`, `latest-dev`, and `sha` 

### 3. Build & Deploy to UAT
- **Purpose:** Generates a Git tag starting with `rc` and increments that number. It will then build and deploy new images to Gold/GoldDR
- **Trigger:** Manual
- **Image Tags:** `latest`, `latest-uat`, `rc##` and `sha` 

### Deploy to Prod
- **Purpose:** Promote the selected image tag from UAT to Prod
- **Trigger:** Manual by doing these steps:
    1. Go to `Releases` on the main Github Page
    1. Click `Draft a new release`
    1. Chose the tag you want to push to prod
    1. Click `Generate release notes`
    1. Give it a title (Default will be the tag which we do not want)
    1. Click `Publish Release`

### Weekly Trivy Image Scans
- **Purpose:** To identify any `HIGH` or `CRITICAL` vulnerabilities in the images. Results are uploaded to the Github Security Tab
- **Trigger:** Automatic on Sundays at 2am

