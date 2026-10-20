# Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
# Copy this directory to src/drivers/tutorial2 before building.
TORCS_BASE := $(abspath ../../..)
MAKE_DEFAULT := $(TORCS_BASE)/Make-default.mk
ROBOT = tutorial2
MODULE = $(ROBOT).so
MODULEDIR = drivers/$(ROBOT)
SOURCES = tutorial2.cpp recovery.cpp practice.cpp
SHIPDIR = drivers/$(ROBOT)
SHIP = tutorial2.xml
SHIPSUBDIRS =
PKGSUBDIRS =

include $(MAKE_DEFAULT)

CXXFLAGS += -std=c++14
tutorial2.o practice.o: recovery.h practice.h
recovery.o: recovery.h
