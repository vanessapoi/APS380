/***************************************************************************

    file                 : rttelem.cpp
    created              : Mon Feb 28 22:38:31 CET 2000
    copyright            : (C) 2000-2026 by Eric Espié, Bernhard Wymann
    email                : berniw@bluewin.ch

 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/

#if 0

/** @file	
    		This is a collection of useful functions for using telemetry in a robot.
		You can see an example of telemetry usage in the human driver.
    @author	<a href=mailto:torcs@free.fr>Eric Espie</a>
    @ingroup	robottools
*/

/** @defgroup telemetry		Telemetry tools for robots.
    The telemetry is only working with Linux.
    <br>The graphs are build by gnuplot.
    @ingroup	robottools
*/

#endif

#include <stdlib.h>
#include <stdio.h>
#ifdef WIN32
#include <windows.h>
#endif
#include <telemetry.h>
#include <robottools.h>
#include <tgf.h>
#include <portability.h>

#if 0
static tTelemItf	tlm;
static tModList		*modlist = (tModList*)NULL;
#endif

/** @defgroup telemetry Robot Telemetry API
    Legacy telemetry wrappers declared in robottools.h. In the current build
    all six functions are no-ops: they do not load a module, retain channel
    pointers, record samples, create files or launch plotting tools.
    @ingroup robottools
 */

/** Legacy telemetry initialization; currently does nothing.
    @ingroup	telemetry
    @param[in] ymin Requested Y minimum; ignored.
    @param[in] ymax Requested Y maximum; ignored.
 */
void RtTelemInit(tdble ymin, tdble ymax)
{
#ifdef later
	const int BUFSIZE = 256;
    char	buf[BUFSIZE];
    tModInfo	*curModInfo;

    memset(&tlm, 0, sizeof(tTelemItf));
    snprintf(buf, BUFSIZE, "%smodules/telemetry/%s.%s", "telemetry", GetLibDir (), DLLEXT);
    if (GfModLoad(TLM_IDENT, buf, &modlist)) return;
    GfOut("--- %s loaded ---\n", modlist->modInfo->name);
    curModInfo = modlist->modInfo;
    curModInfo->fctInit(curModInfo->index, &tlm);

    tlm.init(ymin, ymax);
#endif
}


/** Legacy channel registration; currently does nothing.
    @ingroup	telemetry
    @param[in] name Channel name; ignored.
    @param[in] var Variable address; neither read nor retained.
    @param[in] min Requested minimum; ignored.
    @param[in] max Requested maximum; ignored.
 */
void RtTelemNewChannel(const char * name, tdble * var, tdble min, tdble max)
{
#if 0
    tlm.newChannel(name, var, min, max);
#endif
}

/** Legacy start-recording request; currently creates no file and does nothing.
    @ingroup	telemetry
    @param[in] filename Requested output filename; ignored.
 */
void RtTelemStartMonitoring(const char * filename)
{
#if 0
    tlm.startMonitoring(filename);
#endif
}

/** Legacy stop-recording request; currently does nothing.
    @ingroup	telemetry
 */
void RtTelemStopMonitoring(void)
{
#if 0
    tlm.stopMonitoring();
#endif
}

/** Legacy sample-recording request; currently does nothing.
    @ingroup	telemetry
    @param[in] time Requested sample time in seconds; ignored.
 */
void RtTelemUpdate(double time)
{
#if 0
    tlm.update(time);
#endif
}

/** Legacy telemetry shutdown; currently does nothing.
    @ingroup	telemetry
 */
void RtTelemShutdown(void)
{
#if 0
    tlm.shutdown();
    GfModUnloadList(&modlist);
#endif
}
