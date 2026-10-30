"""BDM1 constrained flux projection; no analytic-reference inputs."""
import numpy as np
from p7_flux_reconstruction import THICKNESS, geometry_balance
from scipy.sparse import bmat
from skfem import (
    Basis,
    BilinearForm,
    ElementTriBDM1,
    ElementTriP0,
    ElementTriP1,
    FacetBasis,
    InteriorFacetBasis,
    LinearForm,
    condense,
    solve,
)
from skfem.helpers import div, dot


def project_bdm(mesh,tags,facets,temperature_nodes,config):
    temperature_nodes = np.asarray(temperature_nodes,dtype=float)
    if temperature_nodes.shape != (mesh.nvertices,) or not np.all(np.isfinite(temperature_nodes)):
        raise ValueError("aligned finite original P1 nodal temperatures required")
    conductivity = np.where(tags == 10,config["k1"],config["k2"])
    sources = np.where(tags == 10,config["s1"],config["s2"])
    primal = Basis(mesh,ElementTriP1(),intorder=6)
    primal_field = primal.interpolate(temperature_nodes)
    rt = Basis(mesh,ElementTriBDM1(),intorder=6)
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
    dofs = rt.facet_dofs
    assert dofs.shape == (2,mesh.nfacets) and rt.N == 2*mesh.nfacets
    fixed_facets = np.unique(np.concatenate([facets[i] for i in (1,2,3)]))
    fixed_dofs = np.unique(dofs[:,fixed_facets])
    boundary_basis = FacetBasis(mesh,ElementTriBDM1(),facets=fixed_facets,intorder=6)
    boundary_primal = FacetBasis(mesh,ElementTriP1(),facets=fixed_facets,intorder=6)
    target = np.zeros(boundary_basis.dx.shape)
    mask = np.isin(fixed_facets,facets[2])
    target[mask] = config["h"]*(boundary_primal.interpolate(temperature_nodes)[mask]
                               -config["ambient_c"])

    @BilinearForm
    def normal_mass(u,v,w):
        return dot(u,w.n)*dot(v,w.n)

    @LinearForm
    def normal_target(v,w):
        return target*dot(v,w.n)

    boundary_matrix = normal_mass.assemble(boundary_basis)
    boundary_load = normal_target.assemble(boundary_basis)
    initial = np.zeros(matrix.shape[0])
    initial[fixed_dofs] = solve(boundary_matrix[fixed_dofs][:,fixed_dofs],
                                boundary_load[fixed_dofs])
    solution = solve(*condense(matrix,right,x=initial,D=fixed_dofs))
    coefficients = solution[:rt.N]
    field = rt.interpolate(coefficients)
    all_facets = np.arange(mesh.nfacets)
    face_basis = FacetBasis(mesh,ElementTriBDM1(),facets=all_facets,intorder=6)
    values = face_basis.interpolate(coefficients)
    trace = np.sum(values*face_basis.normals,axis=0)
    integrated_trace = np.sum(trace*face_basis.dx,axis=1)

    @LinearForm
    def normal_moment(v,w):
        return dot(v,w.n)

    moments = normal_moment.assemble(face_basis)
    dof_integrals = np.sum(moments[dofs]*coefficients[dofs],axis=0)
    qint = integrated_trace
    balance,area = geometry_balance(mesh,qint,sources)
    boundary_actual = boundary_basis.interpolate(coefficients)
    boundary_trace = np.sum(boundary_actual*boundary_basis.normals,axis=0)
    boundary_trace_error = float(np.max(abs(boundary_trace-target)))

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
    side0 = InteriorFacetBasis(mesh,ElementTriBDM1(),facets=interior,side=0,intorder=6)
    side1 = InteriorFacetBasis(mesh,ElementTriBDM1(),facets=interior,side=1,intorder=6)
    jump = np.sum((side0.interpolate(coefficients)-side1.interpolate(coefficients))
                  *side0.normals,axis=0)
    boundary_power = {i:float(THICKNESS*qint[facets[i]].sum()) for i in (1,2,3,4)}
    # Independent face moments reconstruct the faulty integrals without the div matrix.
    interior_dofs = dofs[:,interior].ravel()
    chosen = int(interior_dofs[np.argmax(abs(moments[interior_dofs]
                                            *coefficients[interior_dofs]))])
    bad = coefficients.copy()
    bad[chosen] *= -1
    bad_integrals = np.sum(moments[dofs]*bad[dofs],axis=0)
    bad_balance,_ = geometry_balance(mesh,bad_integrals,sources)
    return dict(rt=rt,field=field,coefficients=coefficients,facet_integrals=qint,
                cell_balance_w=balance,cell_area_m2=area,sources=sources,
                normals=normals,facet_lengths_m=lengths_all,facet_midpoints=midpoint,
                boundary_power_w=boundary_power,
                trace_integral_error_w_per_m=float(np.max(abs(integrated_trace-dof_integrals))),
                boundary_trace_error_w_m2=boundary_trace_error,
                facet_trace=trace,facet_dx=face_basis.dx,
                facet_coordinates=face_basis.global_coordinates(),
                dof_moment_weights=moments,
                normal_error=normal_error,normal_jump_w_per_m2=float(np.max(abs(jump))),
                div_matrix_residual=float(np.max(abs(constraint @ coefficients-load))),
                fault_max_balance_w=float(np.max(abs(bad_balance))),
                fault_dof=chosen,primal_gradient=primal_field.grad)
