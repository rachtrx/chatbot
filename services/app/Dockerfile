# Builder stage
FROM condaforge/mambaforge:latest as builder

WORKDIR /usr/src/app

# Copy environment file and create environment
COPY environment.yml .
RUN mamba env create -f environment.yml

# Final stage
FROM condaforge/mambaforge:latest

ENV DEBIAN_FRONTEND noninteractive

# install cron and tesseract 
RUN apt-get update \
    # && apt-get install -y tesseract-ocr cron curl\
    && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    cron \
    curl \
    postgresql-client \
    tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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

RUN if [ -f /home/app/web/chatbot.db ]; then rm /home/app/web/chatbot.db; fi

# Set user, permissions, and other necessary steps...

RUN chmod +x entrypoint.sh

# # chown all the files to the app user
# RUN chown -R app:app $APP_HOME

RUN python -m spacy download en_core_web_sm

# Set timezone
RUN ln -sf /usr/share/zoneinfo/Asia/Singapore /etc/localtime \
    && echo "Asia/Singapore" > /etc/timezone

# Copy azure_cron.txt file to the cron.d directory
COPY cron/azure_cron.txt /etc/cron.d/azure_cron.txt
 
# Give execution rights on the cron job
RUN chmod 0644 /etc/cron.d/azure_cron.txt

# Apply cron job
RUN crontab /etc/cron.d/azure_cron.txt
 
# Create the log file to be able to run tail
RUN touch /var/log/cron_sync.log

# Run the command on container startup

# # Switch to the app user
# USER app

ENTRYPOINT ["/home/app/web/entrypoint.sh", "es01", "gunicorn", "-w", "4", "--bind", "0.0.0.0:5001", "--timeout", "120", "app:app"]
