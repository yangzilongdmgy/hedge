# -*- coding: utf8 -*-
"""Operators for Poisson problems."""

from __future__ import division

__copyright__ = "Copyright (C) 2007 Andreas Kloeckner"

__license__ = """
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see U{http://www.gnu.org/licenses/}.
"""




import numpy

from hedge.models import Operator
from hedge.second_order import LDGSecondDerivative
import hedge.data
import hedge.iterative




class LaplacianOperatorBase(object):
    def op_template(self, apply_minv, u=None, dir_bc=None, neu_bc=None):
        """
        :param apply_minv: :class:`bool` specifying whether to compute a complete
          divergence operator. If False, the final application of the inverse
          mass operator is skipped. This is used in :meth:`op` in order to reduce
          the scheme :math:`M^{-1} S u = f` to :math:`S u = M f`, so that the mass operator
          only needs to be applied once, when preparing the right hand side
          in :meth:`prepare_rhs`.

          :class:`hedge.models.diffusion.DiffusionOperator` needs this.
        """

        from hedge.optemplate import InverseMassOperator, Field, make_vector_field
        from hedge.second_order import SecondDerivativeTarget

        if u is None: u = Field("u")
        if dir_bc is None: dir_bc = Field("dir_bc")
        if neu_bc is None: neu_bc = Field("neu_bc")

        # strong_form here allows IPDG to reuse the value of grad u.
        grad_tgt = SecondDerivativeTarget(
                self.dimensions, strong_form=True,
                operand=u)

        def grad_bc_getter(tag, expr):
            assert tag == self.dirichlet_tag
            return dir_bc
        self.scheme.grad(grad_tgt,
                bc_getter=grad_bc_getter,
                dirichlet_tags=[self.dirichlet_tag],
                neumann_tags=[self.neumann_tag])

        def apply_diff_tensor(v):
            if isinstance(self.diffusion_tensor, numpy.ndarray):
                sym_diff_tensor = self.diffusion_tensor
            else:
                sym_diff_tensor = (make_vector_field(
                        "diffusion", self.dimensions**2)
                        .reshape(self.dimensions, self.dimensions))

            return numpy.dot(sym_diff_tensor, v)

        div_tgt = SecondDerivativeTarget(
                self.dimensions, strong_form=False,
                operand=apply_diff_tensor(grad_tgt.minv_all))

        def div_bc_getter(tag, expr):
            if tag == self.dirichlet_tag:
                return dir_bc
            elif tag == self.neumann_tag:
                return neu_bc
            else:
                assert False, "divergence bc getter " \
                        "asked for '%s' BC for '%s'" % (tag, expr)

        self.scheme.div(div_tgt,
                div_bc_getter,
                dirichlet_tags=[self.dirichlet_tag],
                neumann_tags=[self.neumann_tag])

        if apply_minv:
            return div_tgt.minv_all
        else:
            return div_tgt.all




class PoissonOperator(Operator, LaplacianOperatorBase):
    """Implements the Local Discontinuous Galerkin (LDG) Method for elliptic
    operators.

    See P. Castillo et al.,
    Local discontinuous Galerkin methods for elliptic problems",
    Communications in Numerical Methods in Engineering 18, no. 1 (2002): 69-75.
    """

    def __init__(self, dimensions, diffusion_tensor=None,
            dirichlet_bc=hedge.data.ConstantGivenFunction(), dirichlet_tag="dirichlet",
            neumann_bc=hedge.data.ConstantGivenFunction(), neumann_tag="neumann",
            scheme=LDGSecondDerivative()):
        self.dimensions = dimensions

        self.scheme = scheme

        self.dirichlet_bc = dirichlet_bc
        self.dirichlet_tag = dirichlet_tag
        self.neumann_bc = neumann_bc
        self.neumann_tag = neumann_tag

        if diffusion_tensor is None:
            diffusion_tensor = numpy.eye(dimensions)
        self.diffusion_tensor = diffusion_tensor

    # bound operator ----------------------------------------------------------
    def bind(self, discr):
        """Return a :class:`BoundPoissonOperator`."""

        assert self.dimensions == discr.dimensions

        from hedge.mesh import check_bc_coverage
        check_bc_coverage(discr.mesh, [self.dirichlet_tag, self.neumann_tag])

        return BoundPoissonOperator(self, discr)




class BoundPoissonOperator(hedge.iterative.OperatorBase):
    """Returned by :meth:`PoissonOperator.bind`."""

    def __init__(self, poisson_op, discr):
        hedge.iterative.OperatorBase.__init__(self)
        self.discr = discr

        pop = self.poisson_op = poisson_op

        op = pop.op_template(
            apply_minv=False, dir_bc=0, neu_bc=0)
        bc_op = pop.op_template(apply_minv=False)

        self.compiled_op = discr.compile(op)
        self.compiled_bc_op = discr.compile(bc_op)

        if not isinstance(pop.diffusion_tensor, numpy.ndarray):
            self.diffusion = pop.diffusion_tensor.volume_interpolant(discr)

        # Check whether use of Poincaré mean-value method is required.
        # (for pure Neumann or pure periodic)

        from hedge.mesh import TAG_ALL
        self.poincare_mean_value_hack = (
                len(self.discr.get_boundary(TAG_ALL).nodes)
                == len(self.discr.get_boundary(poisson_op.neumann_tag).nodes))

    @property
    def dtype(self):
        return self.discr.default_scalar_type

    @property
    def shape(self):
        nodes = len(self.discr)
        return nodes, nodes

    def op(self, u):
        context = {"u": u}
        if not isinstance(self.poisson_op.diffusion_tensor, numpy.ndarray):
            context["diffusion"] = self.diffusion

        result = self.compiled_op(**context)

        if self.poincare_mean_value_hack:
            state_int = self.discr.integral(u)
            mean_state = state_int / self.discr.mesh_volume()
            return result - mean_state * self.discr._mass_ones()
        else:
            return result

    __call__ = op

    def prepare_rhs(self, rhs):
        """Prepare the right-hand side for the linear system op(u)=rhs(f).

        In matrix form, LDG looks like this:

        .. math::
            Mv = Cu + g
            Mf = Av + Bu + h

        where v is the auxiliary vector, u is the argument of the operator, f
        is the result of the grad operator, g and h are inhom boundary data, and
        A,B,C are some operator+lifting matrices.

        .. math::

            M f = A M^{-1}(Cu + g) + Bu + h

        so the linear system looks like

        .. math::

            M f = A M^{-1} Cu + A M^{-1} g + Bu + h
            M f - A M^{-1} g - h = (A M^{-1} C + B)u (*)

        So the right hand side we're putting together here is really

        .. math::

            M f - A M^{-1} g - h

        .. note::

            Resist the temptation to left-multiply by the inverse
            mass matrix, as this will result in a non-symmetric
            matrix, which (e.g.) a conjugate gradient Krylov
            solver will not take well.
        """
        pop = self.poisson_op

        from hedge.optemplate import MassOperator
        return (MassOperator().apply(self.discr, rhs)
            - self.compiled_bc_op(
                u=self.discr.volume_zeros(),
                dir_bc=pop.dirichlet_bc.boundary_interpolant(
                    self.discr, pop.dirichlet_tag), 
                neu_bc=pop.neumann_bc.boundary_interpolant(
                    self.discr, pop.neumann_tag)))




class HelmholtzOperator(PoissonOperator):
    def __init__(self, k, *args, **kwargs):
        PoissonOperator.__init__(self, *args, **kwargs)
        self.k = k

    def op_template(self, apply_minv, u=None, dir_bc=None, neu_bc=None):
        from hedge.optemplate import Field
        if u is None: u = Field("u")

        result = PoissonOperator.op_template(self,
                apply_minv, u, dir_bc, neu_bc)

        if apply_minv:
            return result + self.k**2 * u
        else:
            from hedge.optemplate import MassOperator
            return result + self.k**2 * MassOperator()(u)
