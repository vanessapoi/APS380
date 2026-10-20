# Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
# Assemble the working folder as described on the platform setup page.
TORCS_BASE := $(abspath ../../..)
MAKE_DEFAULT := $(TORCS_BASE)/Make-default.mk
ROBOT ?= tutorial5
MODULE = $(ROBOT).so
MODULEDIR = drivers/$(ROBOT)
SOURCES = $(ROBOT).cpp traffic5.cpp speed4.cpp braking4.cpp recovery4.cpp steering4.cpp geometry4.cpp
SHIPDIR = drivers/$(ROBOT)
SHIP = $(ROBOT).xml
SHIPSUBDIRS =
PKGSUBDIRS =

include $(MAKE_DEFAULT)

CXXFLAGS += -std=c++14
tutorial5.o tutorial5pace.o traffic5.o: traffic5.h speed4.h braking4.h steering4.h geometry4.h recovery4.h
speed4.o: speed4.h braking4.h steering4.h geometry4.h
braking4.o: braking4.h
recovery4.o: recovery4.h
steering4.o: steering4.h geometry4.h
geometry4.o: geometry4.h
