# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# File Author: Dennis Hayrullin                            #
# Date: 2/5/2016                                           #
# MIT Licence                                              #
# ##########################################################

from OpenGL import GLU
import numpy as np
import shapely
from shapely.errors import GEOSException


class GLUTess:
    def __init__(self):
        """
        OpenGL GLU triangulation class
        """
        self.tris = []
        self.pts = []
        self.vertex_index = 0

    def _on_begin_primitive(self, type):
        pass

    def _on_new_vertex(self, vertex):
        self.tris.append(vertex)

    # Force GLU to return separate triangles (GLU_TRIANGLES)
    def _on_edge_flag(self, flag):
        pass

    def _on_combine(self, coords, data, weight):
        return coords[0], coords[1], coords[2]

    @staticmethod
    def _on_error(errno):
        print("GLUTess error:", errno)

    def _on_end_primitive(self):
        pass

    def triangulate(self, polygon):
        """
        Triangulates polygon
        :param polygon: shapely.geometry.polygon
            Polygon to tessellate
        :return: list, list
            Array of triangle vertex indices [t0i0, t0i1, t0i2, t1i0, t1i1, ... ]
            Array of polygon points [(x0, y0), (x1, y1), ... ]
        """
        # GEOS avoids Python callbacks for every vertex. Keep GLU for older GEOS/Shapely
        # and invalid contours that need its intersection/combine handling.
        native_triangulate = getattr(shapely, 'constrained_delaunay_triangles', None)
        if native_triangulate is not None and polygon.is_valid and not polygon.is_empty:
            try:
                triangles = native_triangulate(polygon)
                points = shapely.get_coordinates(triangles).reshape(-1, 4, 2)[:, :3].copy()
                if len(points):
                    a = points[:, 1] - points[:, 0]
                    b = points[:, 2] - points[:, 0]
                    clockwise = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0] < 0
                    points[clockwise, 1], points[clockwise, 2] = \
                        points[clockwise, 2].copy(), points[clockwise, 1].copy()
                    vertices, indices = np.unique(points.reshape(-1, 2), axis=0, return_inverse=True)
                    self.pts = vertices.tolist()
                    self.tris = indices.tolist()
                    return self.tris, self.pts
            except (GEOSException, shapely.errors.UnsupportedGEOSVersionError):
                pass

        # Create tessellation object
        tess = GLU.gluNewTess()

        # Setup callbacks
        GLU.gluTessCallback(tess, GLU.GLU_TESS_BEGIN, self._on_begin_primitive)
        GLU.gluTessCallback(tess, GLU.GLU_TESS_VERTEX, self._on_new_vertex)
        GLU.gluTessCallback(tess, GLU.GLU_TESS_EDGE_FLAG, self._on_edge_flag)
        GLU.gluTessCallback(tess, GLU.GLU_TESS_COMBINE, self._on_combine)
        GLU.gluTessCallback(tess, GLU.GLU_TESS_ERROR, self._on_error)
        GLU.gluTessCallback(tess, GLU.GLU_TESS_END, self._on_end_primitive)

        # Reset data
        del self.tris[:]
        del self.pts[:]
        self.vertex_index = 0

        # Define polygon
        GLU.gluTessBeginPolygon(tess, None)

        def define_contour(contour):
            vertices = list(contour.coords)             # Get vertices coordinates
            if vertices[0] == vertices[-1]:             # Open ring
                vertices = vertices[:-1]

            self.pts += vertices

            GLU.gluTessBeginContour(tess)               # Start contour

            # Set vertices
            for vertex in vertices:
                point = (vertex[0], vertex[1], 0)
                GLU.gluTessVertex(tess, point, self.vertex_index)
                self.vertex_index += 1

            GLU.gluTessEndContour(tess)                 # End contour

        # Polygon exterior
        define_contour(polygon.exterior)

        # Interiors
        for interior in polygon.interiors:
            define_contour(interior)

        # Start tessellation
        GLU.gluTessEndPolygon(tess)

        # Free resources
        GLU.gluDeleteTess(tess)

        # Enforce CCW winding order for OpenGL backface culling compatibility
        # Vectorized numpy approach — process all triangles at once
        if self.tris and self.pts:
            pts = np.array(self.pts, dtype=np.float64)
            tris = np.array(self.tris, dtype=np.uint32).reshape(-1, 3)

            p0 = pts[tris[:, 0]]
            p1 = pts[tris[:, 1]]
            p2 = pts[tris[:, 2]]

            # Cross product Z component: (p1-p0) x (p2-p0)
            cross_z = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - \
                      (p1[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0])

            # Swap indices for clockwise triangles to make them CCW
            cw_mask = cross_z < 0
            tris[cw_mask, 1], tris[cw_mask, 2] = tris[cw_mask, 2].copy(), tris[cw_mask, 1].copy()

            self.tris = tris.ravel().tolist()

        return self.tris, self.pts
