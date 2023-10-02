# Builder stage
FROM condaforge/mambaforge:latest as builder

WORKDIR /usr/src/app

# Copy environment file and create environment
COPY environment.yml .
RUN mamba env create -f environment.yml

# Final stage
FROM condaforge/mambaforge:latest

# create directory for the app user
RUN mkdir -p /home/app

# create the app user
RUN addgroup app && adduser --ingroup app app --system

ENV HOME=/home/app
ENV APP_HOME=/home/app/web
RUN mkdir $APP_HOME
WORKDIR $APP_HOME

# Copy environment from builder stage
COPY --from=builder /opt/conda/envs/chatbot /opt/conda/envs/chatbot

# Adjust PATH to activate the conda environment
ENV PATH /opt/conda/envs/chatbot/bin:$PATH

# Copy application code from builder stage
COPY . $APP_HOME

# Set user, permissions, and other necessary steps...

# chown all the files to the app user
RUN chown -R app:app $APP_HOME

# change to the app user
USER app




