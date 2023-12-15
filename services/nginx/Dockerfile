FROM nginx:1.25

RUN apt-get update \
    && apt-get install -y curl\
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d
COPY wait-for-gunicorn.sh /wait-for-gunicorn.sh
RUN chmod +x /wait-for-gunicorn.sh

CMD ["/wait-for-gunicorn.sh", "http://chatbot:5001", "nginx", "-g", "daemon off;"]