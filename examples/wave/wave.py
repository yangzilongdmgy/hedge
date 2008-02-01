# Hedge - the Hybrid'n'Easy DG Environment
# Copyright (C) 2007 Andreas Kloeckner
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.




import pylinear.array as num
import pylinear.computation as comp
from pytools.arithmetic_container import ArithmeticList, join_fields
from hedge.tools import Rotation, dot




class StrongWaveOperator:
    def __init__(self, discr, source_f=None, flux_type="upwind"):
        self.discr = discr
        self.source_f = source_f

        from hedge.flux import FluxVectorPlaceholder, make_normal

        dim = discr.dimensions
        w = FluxVectorPlaceholder(1+dim)
        u = w[0]
        v = w[1:]
        normal = make_normal(dim)

        flux_weak = join_fields(
                dot(v.avg, normal),
                u.avg * normal)

        if flux_type == "central":
            pass
        elif flux_type == "upwind":
            # see doc/notes/hedge-notes.tm, generalized from 1D
            flux_weak += join_fields(
                    0.5*(u.int-u.ext),
                    0.5*(v.int-v.ext))
        else:
            raise ValueError, "invalid flux type"

        flux_strong = join_fields(
                dot(v.int, normal),
                u.int * normal) - flux_weak

        self.flux = discr.get_flux_operator(flux_strong)

        self.nabla = discr.nabla
        self.mass = discr.mass_operator
        self.m_inv = discr.inverse_mass_operator

    def rhs(self, t, w):
        from hedge.discretization import pair_with_boundary, cache_diff_results

        u = w[0]
        v = w[1:]

        bc = join_fields(
                -self.discr.boundarize_volume_field(u),
                self.discr.boundarize_volume_field(v))

        rhs = (join_fields(
                dot(self.nabla, cache_diff_results(v)), 
                self.nabla*cache_diff_results(u))
                - self.m_inv*(self.flux*w + self.flux*pair_with_boundary(w, bc)))

        if self.source_f is not None:
            rhs[0] += self.source_f(t)

        return rhs




def main() :
    from hedge.element import \
            TriangularElement, \
            TetrahedralElement
    from hedge.timestep import RK4TimeStepper, AdamsBashforthTimeStepper
    from hedge.mesh import \
            make_disk_mesh, \
            make_regular_square_mesh, \
            make_square_mesh, \
            make_ball_mesh
    from hedge.visualization import SiloVisualizer, VtkVisualizer
    from pytools.stopwatch import Job
    from math import sin, cos, pi, exp, sqrt
    from hedge.parallel import guess_parallelization_context

    pcon = guess_parallelization_context()

    dim = 3

    if dim == 2:
        if pcon.is_head_rank:
            #mesh = make_disk_mesh()
            #mesh = make_regular_square_mesh(
                    #n=9, periodicity=(True,True))
            mesh = make_square_mesh(max_area=0.008)
            #mesh.transform(Rotation(pi/8))
        el_class = TriangularElement
    elif dim == 3:
        if pcon.is_head_rank:
            mesh = make_ball_mesh(max_volume=0.001)
        el_class = TetrahedralElement
    else:
        raise RuntimeError, "bad number of dimensions"

    if pcon.is_head_rank:
        print "%d elements" % len(mesh.elements)
        mesh_data = pcon.distribute_mesh(mesh)
    else:
        mesh_data = pcon.receive_mesh()

    discr = pcon.make_discretization(mesh_data, el_class(3))
    stepper = RK4TimeStepper()
    #stepper = AdamsBashforthTimeStepper(1)
    vis = VtkVisualizer(discr, pcon, "fld")

    dt = discr.dt_factor(1)
    nsteps = int(10/dt)
    if pcon.is_head_rank:
        print "dt", dt
        print "nsteps", nsteps

    def source_u(x):
        return exp(-x*x*256)

    source_u_vec = discr.interpolate_volume_function(source_u)

    def source_vec_getter(t):
        if t > 0.1:
            return discr.volume_zeros()
        else:
            return source_u_vec

    op = StrongWaveOperator(discr, source_vec_getter)
    fields = ArithmeticList([discr.volume_zeros()]) # u
    fields.extend([discr.volume_zeros() for i in range(discr.dimensions)]) # v

    # diagnostics setup -------------------------------------------------------
    from pytools.log import LogManager, \
            add_general_quantities, \
            add_simulation_quantities, \
            add_run_info

    logmgr = LogManager("advection.dat", pcon.communicator)
    add_run_info(logmgr)
    add_general_quantities(logmgr)
    add_simulation_quantities(logmgr, dt)
    discr.add_instrumentation(logmgr)

    from pytools.log import IntervalTimer
    vis_timer = IntervalTimer("t_vis", "Time spent visualizing")
    logmgr.add_quantity(vis_timer)
    stepper.add_instrumentation(logmgr)

    from hedge.log import Integral, L1Norm, L2Norm, VariableGetter
    u_getter = VariableGetter(locals(), "fields", 0)
    logmgr.add_quantity(L1Norm(u_getter, discr, name="l1_u"))
    logmgr.add_quantity(L2Norm(u_getter, discr, name="l2_u"))

    logmgr.add_watches(["step.max", "t_sim.max", "l2_u", "t_step.max"])

    # timestep loop -----------------------------------------------------------
    for step in range(nsteps):
        logmgr.tick()

        t = step*dt

        if step % 1 == 0:
            visf = vis.make_file("fld-%04d" % step)
            vis.add_data(visf,
                    [
                        ("u", fields[0]),
                        ("v", fields[1:]), 
                    ],
                    time=t,
                    step=step)
            visf.close()

        fields = stepper(fields, t, dt, op.rhs)

    vis.close()

    logmgr.tick()
    logmgr.save()

if __name__ == "__main__":
    #import cProfile as profile
    #profile.run("main()", "wave2d.prof")
    main()

