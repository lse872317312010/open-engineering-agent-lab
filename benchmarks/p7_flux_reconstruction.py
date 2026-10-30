"""RT0 constrained flux projection; no analytic-reference imports or fitting."""
import numpy as np
from scipy.sparse import bmat
from skfem import (
    Basis,
    BilinearForm,
    ElementTriP0,
    ElementTriP1,
    ElementTriRT0,
    FacetBasis,
    InteriorFacetBasis,
    LinearForm,
    condense,
    solve,
)
from skfem.helpers import div, dot

THICKNESS = .01


def geometry_balance(mesh, facet_integrals, sources):
    points = mesh.p[:,mesh.t]
    area = abs((points[0,1]-points[0,0])*(points[1,2]-points[1,0])
               -(points[1,1]-points[1,0])*(points[0,2]-points[0,0]))/2
    sign = np.where(mesh.f2t[0,mesh.t2f] == np.arange(mesh.nelements)[None,:],1.,-1.)
    net = np.sum(sign*facet_integrals[mesh.t2f],axis=0)
    return THICKNESS*(net-sources*area),area


def project_flux(mesh,tags,facets,temperature_nodes,config):
    temperature_nodes = np.asarray(temperature_nodes,dtype=float)
    if temperature_nodes.shape != (mesh.nvertices,) or not np.all(np.isfinite(temperature_nodes)):
        raise ValueError("aligned finite original P1 nodal temperatures required")
    conductivity = np.where(tags == 10,config["k1"],config["k2"])
    sources = np.where(tags == 10,config["s1"],config["s2"])
    primal = Basis(mesh,ElementTriP1(),intorder=6)
    primal_field = primal.interpolate(temperature_nodes)
    rt = Basis(mesh,ElementTriRT0(),intorder=6)
    constant = Basis(mesh,ElementTriP0(),intorder=6)

    @BilinearForm
    def metric(u,v,w):
        return dot(u,v)/conductivity[:,None]

    @BilinearForm
    def divergence(u,v,w):
        return div(u)*v

    @LinearForm
    def objective(v,w):
        return -dot(primal_field.grad,v)

    @LinearForm
    def source(v,w):
        return sources[:,None]*v

    mass = metric.assemble(rt)
    constraint = divergence.assemble(rt,constant)
    load = source.assemble(constant)
    matrix = bmat([[mass,constraint.T],[constraint,None]],format="csr")
    right = np.r_[objective.assemble(rt),load]
    dofs = rt.facet_dofs[0]
    assert len(dofs) == mesh.nfacets and rt.N == mesh.nfacets
    fixed_facets = np.unique(np.concatenate([facets[i] for i in (1,2,3)]))
    fixed_dofs = dofs[fixed_facets]
    initial = np.zeros(matrix.shape[0])
    right_nodes = mesh.facets[:,facets[2]]
    lengths = np.linalg.norm(mesh.p[:,right_nodes[1]]-mesh.p[:,right_nodes[0]],axis=0)
    initial[dofs[facets[2]]] = config["h"]*(
        temperature_nodes[right_nodes].mean(axis=0)-config["ambient_c"])*lengths
    solution = solve(*condense(matrix,right,x=initial,D=fixed_dofs))
    coefficients = solution[:rt.N]
    field = rt.interpolate(coefficients)
    qint = coefficients[dofs]
    balance,area = geometry_balance(mesh,qint,sources)
    all_facets = np.arange(mesh.nfacets)
    face_basis = FacetBasis(mesh,ElementTriRT0(),facets=all_facets,intorder=6)
    values = face_basis.interpolate(coefficients)
    trace = np.sum(values*face_basis.normals,axis=0)
    integrated_trace = np.sum(trace*face_basis.dx,axis=1)
    # Independent outward normals from geometry and the first adjacent cell.
    edges = mesh.p[:,mesh.facets[1]]-mesh.p[:,mesh.facets[0]]
    lengths_all = np.linalg.norm(edges,axis=0)
    normals = np.array([edges[1],-edges[0]])/lengths_all
    midpoint = mesh.p[:,mesh.facets].mean(axis=1)
    centers = mesh.p[:,mesh.t[:,mesh.f2t[0]]].mean(axis=1)
    flip = np.sum(normals*(midpoint-centers),axis=0) < 0
    normals[:,flip] *= -1
    normal_error = float(np.max(abs(normals[:,:,None]-face_basis.normals)))
    interior = np.flatnonzero(mesh.f2t[1] >= 0)
    side0 = InteriorFacetBasis(mesh,ElementTriRT0(),facets=interior,side=0,intorder=6)
    side1 = InteriorFacetBasis(mesh,ElementTriRT0(),facets=interior,side=1,intorder=6)
    jump = np.sum((side0.interpolate(coefficients)-side1.interpolate(coefficients))
                  *side0.normals,axis=0)
    boundary_power = {i:float(THICKNESS*qint[facets[i]].sum()) for i in (1,2,3,4)}
    # Flip a real nonzero interior degree of freedom; audit without the div matrix.
    bad = qint.copy()
    chosen = int(interior[np.argmax(abs(qint[interior]))])
    bad[chosen] *= -1
    bad_balance,_ = geometry_balance(mesh,bad,sources)
    return dict(rt=rt,field=field,coefficients=coefficients,facet_integrals=qint,
                cell_balance_w=balance,cell_area_m2=area,sources=sources,
                normals=normals,facet_lengths_m=lengths_all,facet_midpoints=midpoint,
                boundary_power_w=boundary_power,
                trace_integral_error_w_per_m=float(np.max(abs(integrated_trace-qint))),
                normal_error=normal_error,normal_jump_w_per_m2=float(np.max(abs(jump))),
                div_matrix_residual=float(np.max(abs(constraint @ coefficients-load))),
                fault_max_balance_w=float(np.max(abs(bad_balance))),
                fault_facet=chosen,primal_gradient=primal_field.grad)
