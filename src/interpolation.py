from __future__ import division
import pylinear.array as num
import pylinear.operator as op
from pytools import FunctionValueCache
import pymbolic




def newton_interpolation_coefficients(x, y):
    assert len(x) == len(y)
    n = len(y)
    divided_differences = [y]
    last = y

    for step in range(1, n):
        next = [(last[i+1]-last[i])/(x[i+step]-x[i])
                for i in range(n-step)]
        divided_differences.append(next)
        last = next

    return [dd_col[-1] for dd_col in divided_differences]




def newton_interpolation_polynomial(x, y):
    coeff = newton_interpolation_coefficients(x, y)

    var_x = pymbolic.var("x")
    linear_factors = [
            pymbolic.Polynomial(var_x, ((0, pt), (1, 1)))
            for pt in x]
    pyramid_linear_factors = [1]
    for l in linear_factors:
        pyramid_linear_factors.append(
                pyramid_linear_factors[-1]*l)

    return pymbolic.linear_combination(coeff, pyramid_linear_factors)




def newton_interpolation_function(x, y):
    return pymbolic.compile(newton_interpolation_polynomial(x, y))