"""Conforming OCC partition of a declared annulus by the public winding polygons."""
import json

import gmsh
import meshio
import numpy as np
from p7_winding_heat import SOURCE, SOURCE_SHA, digest
from skfem import MeshTri


def build_mesh(size, folder):
    if digest(SOURCE) != SOURCE_SHA:
        raise ValueError("public geometry SHA mismatch")
    data = json.loads(SOURCE.read_text(encoding="utf-8"))["geometry"]
    surfaces = data["surfaces"][1:25]
    if len(surfaces) != 24:
        raise ValueError("24 public winding regions required")
    folder.mkdir(parents=True, exist_ok=True)
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.logger.start()
    try:
        gmsh.model.add("stator")
        occ = gmsh.model.occ
        disk = occ.addDisk(0, 0, 0, .05, .05)
        bore = occ.addDisk(0, 0, 0, .02785, .02785)
        domain, _ = occ.cut([(2, disk)], [(2, bore)])
        vertices, edges = {}, {}

        def polygon(points):
            ids = []
            for xy in points:
                key = tuple(np.round(xy, 12))
                if key not in vertices:
                    vertices[key] = occ.addPoint(*key, 0.)
                ids.append(vertices[key])
            if ids[0] == ids[-1]:
                ids.pop()
            lines = []
            for a, b in zip(ids, ids[1:]+ids[:1], strict=True):
                if a == b:
                    raise ValueError("degenerate winding edge")
                key = min(a, b), max(a, b)
                if key not in edges:
                    edges[key] = occ.addLine(*key)
                lines.append(edges[key] if a < b else -edges[key])
            return occ.addPlaneSurface([occ.addCurveLoop(lines)])

        fragments, mapping = occ.fragment(domain, [(2, polygon(s["points"])) for s in surfaces])
        inside = {tag for dim, tag in mapping[0] if dim == 2}
        groups = [{tag for dim, tag in m if dim == 2} & inside for m in mapping[1:]]
        if any(not g for g in groups) or sum(map(len, groups)) != len(set.union(*groups)):
            raise ValueError("missing or overlapping winding partitions")
        core = inside-set.union(*groups)
        occ.remove([(d, t) for d, t in fragments if d == 2 and t not in inside], recursive=True)
        occ.synchronize()
        areas = []
        for tag, entities in enumerate([core]+groups, 1):
            gmsh.model.addPhysicalGroup(2, sorted(entities), tag)
            areas.append(sum(occ.getMass(2, e) for e in entities))
        boundary = gmsh.model.getBoundary([(2, s) for s in inside],
                                         combined=True, oriented=False)
        outer = [t for d, t in boundary if d == 1 and
                 max(abs(x) for x in gmsh.model.getBoundingBox(1, t)) > .0499]
        gmsh.model.addPhysicalGroup(1, outer, 100)
        for key, value in {"Mesh.MeshSizeMin": size, "Mesh.MeshSizeMax": size,
                           "Mesh.MeshSizeFromPoints": 0, "Mesh.MeshSizeFromCurvature": 0,
                           "Mesh.MeshSizeExtendFromBoundary": 0, "Mesh.ElementOrder": 1,
                           "Mesh.MshFileVersion": 2.2, "General.NumThreads": 1,
                           "Mesh.RandomFactor": 0}.items():
            gmsh.option.setNumber(key, value)
        gmsh.model.mesh.generate(2)
        gmsh.write(str(folder / "stator.msh"))
        gmsh.write(str(folder / "stator.brep"))
        (folder / "gmsh.log").write_text("\n".join(gmsh.logger.get()), encoding="utf-8")
    finally:
        gmsh.logger.stop()
        gmsh.finalize()
    raw = meshio.read(folder / "stator.msh")
    triangles = raw.cells_dict["triangle"]
    used = np.unique(triangles)
    remap = np.full(len(raw.points), -1)
    remap[used] = np.arange(len(used))
    mesh = MeshTri(raw.points[used, :2].T, remap[triangles].T)
    tags = raw.cell_data_dict["gmsh:physical"]["triangle"]
    lookup = {tuple(sorted(p)): i for i, p in enumerate(mesh.facets.T)}
    outer = np.array([lookup[tuple(sorted(p))] for p in remap[raw.cells_dict["line"]]])
    data["native_areas_m2"] = areas
    return mesh, tags, outer, data


if __name__ == "__main__":
    from p7_winding_heat import ROOT

    mesh, tags, outer, data = build_mesh(.004, ROOT / "outputs/stator-partition-probe")
    print(mesh, data["native_areas_m2"][:3])
