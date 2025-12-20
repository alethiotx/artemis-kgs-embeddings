FROM nvidia/cuda:12.6.2-cudnn-runtime-ubuntu22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3-pip curl

RUN apt-get clean
RUN rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python3 -m pip install --no-cache-dir \ 
    -r requirements.txt

RUN find . -name "__pycache__" -type d -exec rm -rf {} +
RUN rm -rf *.egg-info
