## Setting Up the Environment

To set up the development environment, we utilize Docker Compose. This allows for easy management of the application's services, networks, and volumes. .env files are found within the chatbot_app container

### Starting the Environment in Development

1. **Build and Run Containers:** To build and run the Docker containers as defined in the `docker-compose.yml` file, execute the following command in your terminal:

   ```sh
   docker-compose -f docker-compose.yml up --build

### Starting the Environment in Production

2. Use the 'docker-compose.prod.yml' file in the 'controller' folder instead to start both the chatbot and inventory services. Execute the command:

    ```sh
    docker-compose -f docker-compose.prod.yml up --build -d
