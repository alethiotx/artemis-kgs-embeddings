FROM nvidia/cuda:12.6.2-cudnn-runtime-ubuntu22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3-pip curl

COPY requirements.txt .

RUN python3 -m pip install -r requirements.txt

# # Add nextflow scripts to the container
# COPY ./bin /usr/local/bin