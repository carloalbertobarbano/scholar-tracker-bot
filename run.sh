#!/bin/sh

DATA_DIR=$(pwd)/data
CONFIG_FILE=$(pwd)/conf.json

docker run --rm -v ${DATA_DIR}:/app/data -v ${CONFIG_FILE}:/app/conf.json ghcr.io/carloalbertobarbano/scholar-tracker-bot:main