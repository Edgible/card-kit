# Image for the tools that work on repo files. run builds it on first use and
# again whenever this file changes. The tool scripts are not copied in; run mounts
# the kit, so a change to a script needs no rebuild.
# A tool that checks the machine a card runs on does not use this image.

FROM python:3.12-slim

RUN pip install --no-cache-dir \
    pyyaml==6.0.3 \
    jsonschema==4.26.0
