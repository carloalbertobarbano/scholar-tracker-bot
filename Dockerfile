FROM python:3.10.16-bullseye

# Copy requirements
RUN mkdir /app
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy app
COPY *.py /app/

# Set working directory
WORKDIR /app

# Run app
CMD ["python", "main.py"]