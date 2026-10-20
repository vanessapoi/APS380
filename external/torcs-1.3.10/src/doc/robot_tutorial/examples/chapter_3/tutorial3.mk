# Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
# Copy this directory to src/drivers/tutorial3 before building.
TORCS_BASE := $(abspath ../../..)
MAKE_DEFAULT := $(TORCS_BASE)/Make-default.mk
ROBOT = tutorial3
MODULE = $(ROBOT).so
MODULEDIR = drivers/$(ROBOT)
SOURCES = tutorial3.cpp speed.cpp braking.cpp recovery3.cpp
SHIPDIR = drivers/$(ROBOT)
SHIP = tutorial3.xml
SHIPSUBDIRS =
PKGSUBDIRS =

include $(MAKE_DEFAULT)

CXXFLAGS += -std=c++14
tutorial3.o: speed.h braking.h recovery3.h
speed.o: speed.h braking.h
braking.o: braking.h
recovery3.o: recovery3.h
