def _three_vector(x):
    if len(x) == 3:
        return x
    elif len(x) == 2:
        return x[0], x[1], 0.
    elif len(x) == 1:
        return x[0], 0, 0.





class VtkVisualizer:
    def __init__(self, discr):
        from pyvtk import PolyData

        points = [_three_vector(p) for p in discr.points]
        polygons = []

        for eg in discr.element_groups:
            ldis = eg.local_discretization
            for el, (el_start, el_stop) in zip(eg.members, eg.ranges):
                polygons += [[el_start+j for j in element] 
                        for element in ldis.generate_submesh_indices()]

        self.structure = PolyData(points=points, polygons=polygons)

    def __call__(self, filename, fields=[], vectors=[], description="Hedge visualization"):
        from pyvtk import PointData, VtkData, Scalars, Vectors
        import numpy

        pdatalist = [
                Scalars(numpy.array(field), name=name, lookup_table="default") 
                for name, field in fields
                ] + [
                Vectors([_three_vector(v) for v in field], name=name)
                for name, field in vectors]
        vtk = VtkData(self.structure, "Hedge visualization", PointData(*pdatalist))
        vtk.tofile(filename)




class SiloVisualizer:
    def __init__(self, discr):
        from pyvtk import PolyData
        from pytools import flatten

        self.coords = flatten(
                [p[d] for p in discr.points] for d in range(discr.dimensions))

        polygons = []

        # FIXME enforce ccw numbering?

        for eg in discr.element_groups:
            ldis = eg.local_discretization
            for el, (el_start, el_stop) in zip(eg.members, eg.ranges):
                polygons += [[el_start+j for j in element] 
                        for element in ldis.generate_submesh_indices()]

        self.nodelist = flatten(polygons)
        self.shapesize = [3]
        self.shapecounts = [len(polygons)]
        self.nshapetypes = 1
        self.nzones = len(polygons)
        self.ndims = discr.dimensions

    def __call__(self, filename, fields=[], vectors=[], description="Hedge visualization"):
        from hedge._silo import DBfile, symbols
        s = symbols()
        db = DBfile(filename, s["DB_CLOBBER"], s["DB_LOCAL"], description, s["DB_PDB"])
        db.PutZonelist("zonelist", self.nzones, self.ndims, self.nodelist,
                self.shapesize, self.shapecounts)
        db.PutUcdmesh("mesh", self.ndims, [], self.coords, self.nzones,
                "zonelist", None)
        for name, field in fields:
            db.PutUcdvar1(name, "mesh", field, self.nzones, symbols()["DB_NODECENT"])
        del db

