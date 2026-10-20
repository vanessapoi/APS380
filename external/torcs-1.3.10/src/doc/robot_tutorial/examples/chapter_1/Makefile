# Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
# Copy this directory to src/drivers/tutorial1 before building.
TORCS_BASE := $(abspath ../../..)
MAKE_DEFAULT := $(TORCS_BASE)/Make-default.mk
CHECKPOINT ?= driving

ifeq ($(filter $(CHECKPOINT),skeleton driving),)
$(error CHECKPOINT must be skeleton or driving)
endif

ROBOT = tutorial1
MODULE = $(ROBOT).so
MODULEDIR = drivers/$(ROBOT)
SOURCES = tutorial1.cpp $(CHECKPOINT).cpp
SHIPDIR = drivers/$(ROBOT)
SHIP = tutorial1.xml
SHIPSUBDIRS =
PKGSUBDIRS =

include $(MAKE_DEFAULT)

CXXFLAGS += -std=c++14
# Relink when switching checkpoints, even if both object files already exist.
.PHONY: checkpoint
$(MODULE): checkpoint
tutorial1.o skeleton.o driving.o: driver.h
