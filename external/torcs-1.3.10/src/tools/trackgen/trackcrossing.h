/***************************************************************************

    file                 : trackcrossing.h
    created              : Sun Aug 2 2026
    copyright            : (C) 2026 by Bernhard Wymann
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

/** @file
    @brief Automatic grade-separated track-crossing geometry.
 */

#ifndef _TRACKCROSSING_H_
#define _TRACKCROSSING_H_

#include <stdio.h>

#include <string>
#include <vector>

#include <track.h>


/** @brief User-configurable dimensions for generated crossing geometry. */
struct TrackCrossingSettings
{
	tdble socketGap;        /**< Gap outside each lower-track boundary, in metres. */
	tdble bridgeThickness;  /**< Minimum vertical bridge thickness, in metres. */
};


/** @brief Serialized AC3D vertex and texture coordinates. */
struct TrackCrossingPoint
{
	double x;  /**< TORCS global X coordinate. */
	double y;  /**< TORCS global Y coordinate. */
	double z;  /**< TORCS global elevation. */
	double u;  /**< AC3D texture U coordinate. */
	double v;  /**< AC3D texture V coordinate. */
};


/** @brief Indices of one triangle in a crossing object's vertex array. */
struct TrackCrossingTriangle
{
	int vertex[3];
};


/** @brief One textured AC3D polygon object in a generated crossing. */
struct TrackCrossingObject
{
	std::string name;                             /**< Stable AC3D object name. */
	std::string texture;                          /**< AC3D texture file name. */
	std::vector<TrackCrossingPoint> vertices;     /**< Object-local vertices. */
	std::vector<TrackCrossingTriangle> triangles; /**< Triangle vertex indices. */
};


/** @brief Geometry and diagnostic measurements for one accepted crossing. */
struct TrackCrossingGeometry
{
	int upperSegmentId;                 /**< Main segment above the crossing. */
	int lowerSegmentId;                 /**< Main segment below the crossing. */
	double crossingX;                   /**< Centerline intersection global X. */
	double crossingY;                   /**< Centerline intersection global Y. */
	double undersideZ;                  /**< Constant bridge underside elevation. */
	double minimumUpperZ;               /**< Lowest sampled upper-track surface. */
	double minimumBridgeThickness;      /**< Measured minimum bridge thickness. */
	double measuredSocketGap[2];        /**< Right and left realized socket gaps. */
	TrackCrossingObject underside;      /**< Downward-facing bridge soffit. */
	TrackCrossingObject bridgeRight;    /**< Right fascia, including coplanar portal extensions. */
	TrackCrossingObject bridgeLeft;     /**< Left fascia, including coplanar portal extensions. */
	TrackCrossingObject socketRight;    /**< Vertical right lower-track wall. */
	TrackCrossingObject socketLeft;     /**< Vertical left lower-track wall. */
	TrackCrossingObject filler[2][2];   /**< Portal returns indexed by upper side, then lower side. */
	TrackCrossingObject floorRight;     /**< Right lower-track gap closure. */
	TrackCrossingObject floorLeft;      /**< Left lower-track gap closure. */
	TrackCrossingObject terrainMask;    /**< Non-rendered portal footprint closures. */
};


/** @brief Complete result of automatic crossing detection and construction. */
struct TrackCrossingModel
{
	int candidateCount; /**< Plan intersections before elevation and clearance checks. */
	TrackCrossingSettings settings; /**< Validated settings used for this model. */
	std::vector<TrackCrossingGeometry> crossings; /**< Accepted crossings. */

	TrackCrossingModel() : candidateCount(0)
	{
		settings.socketGap = 0.5f;
		settings.bridgeThickness = 1.0f;
	}
};


/** @brief Read and validate crossing geometry settings.
    @param[in] trackHandle Parameter handle for the track XML.
    @param[out] settings Validated settings with defaults applied.
    @param[out] errorMessage Optional buffer receiving an error description.
    @param[in] errorMessageSize Size of @p errorMessage in bytes.
    @return 0 on success, -1 for a missing handle or invalid setting.
 */
int ReadTrackCrossingSettings(void *trackHandle,
	                         TrackCrossingSettings *settings,
	                         char *errorMessage, size_t errorMessageSize);

/** @brief Detect crossings and construct all accepted track-owned geometry.
    @param[in] track Closed track structure with graphic extensions.
    @param[in] trackHandle Optional parameter handle used to resolve textures.
    @param[in] trackStep Sampling distance used by the normal track renderer.
    @param[in] settings Validated crossing dimensions.
    @param[out] model Replaced with candidate counts and accepted crossings.
    @param[out] errorMessage Optional buffer receiving a fatal error description.
    @param[in] errorMessageSize Size of @p errorMessage in bytes.
    @return 0 after detection, -1 for invalid input or allocation failure.
 */
int BuildTrackCrossingModel(tTrack *track, void *trackHandle,
	                       tdble trackStep,
	                       const TrackCrossingSettings *settings,
	                       TrackCrossingModel *model,
	                       char *errorMessage, size_t errorMessageSize);

/** @brief Write crossing groups below an already-open track hierarchy.
    @param[in,out] acFile Destination AC3D stream.
    @param[in] model Crossing model to serialize; may be NULL.
 */
void WriteTrackCrossingModel(FILE *acFile, const TrackCrossingModel *model);

#endif /* _TRACKCROSSING_H_ */
