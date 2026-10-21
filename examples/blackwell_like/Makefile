ROOT_DIR := $(realpath ../..)
include $(ROOT_DIR)/config.mk

PYTHON ?= python3
DRIVER ?= simx
CASE ?= fp8

.PHONY: run list
run:
	$(PYTHON) $(VORTEX_HOME)/examples/blackwell_like/study.py --build $(ROOT_DIR) --driver $(DRIVER) --case $(CASE)

list:
	$(PYTHON) $(VORTEX_HOME)/examples/blackwell_like/study.py --list
