# Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
# Copy this directory to src/drivers/tutorial4 before building.
TORCS_BASE := $(abspath ../../..)
MAKE_DEFAULT := $(TORCS_BASE)/Make-default.mk
ROBOT = tutorial4
MODULE = $(ROBOT).so
MODULEDIR = drivers/$(ROBOT)
SOURCES = tutorial4.cpp speed4.cpp braking4.cpp recovery4.cpp steering4.cpp geometry4.cpp
SHIPDIR = drivers/$(ROBOT)
SHIP = tutorial4.xml
SHIPSUBDIRS =
PKGSUBDIRS =

include $(MAKE_DEFAULT)

CXXFLAGS += -std=c++14
tutorial4.o: speed4.h braking4.h recovery4.h
speed4.o: speed4.h braking4.h steering4.h geometry4.h
braking4.o: braking4.h
recovery4.o: recovery4.h
steering4.o: steering4.h geometry4.h
geometry4.o: geometry4.h
