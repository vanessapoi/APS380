# Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
# Copy the complete directory to src/drivers/tutoriala before building.
TORCS_BASE := $(abspath ../../..)
MAKE_DEFAULT := $(TORCS_BASE)/Make-default.mk
ROBOT = tutoriala
MODULE = $(ROBOT).so
MODULEDIR = drivers/$(ROBOT)
SOURCES = settings.cpp tutoriala.cpp pit.cpp spline.cpp traffic.cpp speed.cpp braking.cpp recovery.cpp steering.cpp geometry.cpp
SHIPDIR = drivers/$(ROBOT)
SHIP = tutoriala.xml default.xml g-track-1.xml
SHIPSUBDIRS =
PKGSUBDIRS =

include $(MAKE_DEFAULT)

CXXFLAGS += -std=c++14
tutoriala.o pit.o: pit.h spline.h traffic.h speed.h braking.h steering.h geometry.h recovery.h
traffic.o: traffic.h speed.h braking.h steering.h geometry.h
speed.o: speed.h braking.h steering.h geometry.h
braking.o: braking.h
recovery.o: recovery.h
steering.o: steering.h geometry.h
geometry.o: geometry.h
spline.o: spline.h

settings.o tutoriala.o: settings.h
settings.o: pit.h speed.h
