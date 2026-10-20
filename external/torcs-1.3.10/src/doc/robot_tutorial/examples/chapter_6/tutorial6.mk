# Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
# Copy the complete directory to src/drivers/tutorial6 before building.
TORCS_BASE := $(abspath ../../..)
MAKE_DEFAULT := $(TORCS_BASE)/Make-default.mk
ROBOT = tutorial6
MODULE = $(ROBOT).so
MODULEDIR = drivers/$(ROBOT)
SOURCES = tutorial6.cpp pit.cpp spline.cpp traffic.cpp speed.cpp braking.cpp recovery.cpp steering.cpp geometry.cpp
SHIPDIR = drivers/$(ROBOT)
SHIP = tutorial6.xml
SHIPSUBDIRS =
PKGSUBDIRS =

include $(MAKE_DEFAULT)

CXXFLAGS += -std=c++14
tutorial6.o pit.o: pit.h spline.h traffic.h speed.h braking.h steering.h geometry.h recovery.h
traffic.o: traffic.h speed.h braking.h steering.h geometry.h
speed.o: speed.h braking.h steering.h geometry.h
braking.o: braking.h
recovery.o: recovery.h
steering.o: steering.h geometry.h
geometry.o: geometry.h
spline.o: spline.h
