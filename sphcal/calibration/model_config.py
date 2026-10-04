"""
Configuration of the correction map as a sum of tensor-product B-spline terms,
and construction of the model from a configuration and the sample inputs.

The configuration is deliberately a-theoretical: it names which inputs each
term depends on and how many knot intervals it has, nothing about functional
form. Knots are placed either uniformly over the input's bounds or at
quantiles of the sample inputs (so that depth, whose samples are unevenly
spread, gets knots where the data are). Section 6 of
docs/design/code_design.md gives the default.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sphcal.calibration.samples import INPUT_NAMES, INPUT_UNITS
from sphcal.spline.basis import BSplineBasis1D
from sphcal.spline.model import InputSpec, SumOfTermsSpline
from sphcal.spline.term import TensorTerm


@dataclass(frozen=True)
class TermSpec:
    name: str
    input_indices: tuple[int, ...]
    intervals: tuple[int, ...]
    degree: int = 3
    penalty_order: int = 2
    initial_smoothing: float = 1.0
    """Starting smoothing parameter for every dimension of the term, before GCV."""


@dataclass(frozen=True)
class ModelConfiguration:
    terms: tuple[TermSpec, ...]
    knot_placement: dict = field(default_factory=lambda: {"range": "quantile"})
    """Per input name, "uniform" or "quantile"; inputs not listed are uniform."""
    range_bound_margin_fraction: float = 0.02
    """The range input's bounds are the sample extremes widened by this fraction."""
    slope_bound: float = 1.5
    """Bound on |s_u| and |s_v| (tan of about 56 degrees); samples beyond the
    incidence cut-off never enter, so this only needs to exceed tan(cut-off)."""
    curvature_upper_per_mm: float = 1.0 / 20.0
    """Upper bound of the curvature input (a 20 mm sphere); the lower bound is 0."""


def default_configuration(include_full_interaction: bool = False) -> ModelConfiguration:
    """The default of design section 6: position, slope and curvature terms."""
    terms = [
        TermSpec("position", (0, 1, 2), (8, 6, 6)),
        TermSpec("slope", (3, 4, 2), (6, 6, 4)),
        TermSpec("curvature", (5, 3, 4), (1, 4, 4), degree=1),
    ]
    if include_full_interaction:
        terms.append(TermSpec("interaction", (0, 1, 2, 3, 4), (4, 3, 3, 3, 3)))
    return ModelConfiguration(tuple(terms))


def noread_configuration() -> ModelConfiguration:
    """Terms for the read-probability map (the logit of the read fraction)."""
    return ModelConfiguration((TermSpec("position", (0, 1, 2), (4, 3, 4)),
                               TermSpec("slope", (3, 4, 2), (8, 8, 3)),
                               TermSpec("curvature", (5, 3, 4), (1, 3, 3), degree=1)),
                              slope_bound=4.0)


def input_bounds(config: ModelConfiguration, inputs: np.ndarray, image_width: int, image_height: int) -> list[InputSpec]:
    """Bounds of the six inputs: pixels from the image size, range from the data, slopes and curvature from the configuration."""
    range_values = inputs[:, 2]
    span = range_values.max() - range_values.min()
    margin = config.range_bound_margin_fraction * span
    return [
        InputSpec("u", 0.0, float(image_width - 1), INPUT_UNITS[0]),
        InputSpec("v", 0.0, float(image_height - 1), INPUT_UNITS[1]),
        InputSpec("range", float(range_values.min() - margin), float(range_values.max() + margin), INPUT_UNITS[2]),
        InputSpec("slope_u", -config.slope_bound, config.slope_bound, INPUT_UNITS[3]),
        InputSpec("slope_v", -config.slope_bound, config.slope_bound, INPUT_UNITS[4]),
        InputSpec("curvature", 0.0, config.curvature_upper_per_mm, INPUT_UNITS[5]),
    ]


def build_model(config: ModelConfiguration, inputs: np.ndarray, image_width: int, image_height: int,
                metadata: dict | None = None) -> SumOfTermsSpline:
    """A SumOfTermsSpline with zero coefficients, ready to be fitted."""
    specs = input_bounds(config, inputs, image_width, image_height)
    terms = []
    for term_spec in config.terms:
        bases = []
        for input_index, n_intervals in zip(term_spec.input_indices, term_spec.intervals):
            spec = specs[input_index]
            placement = config.knot_placement.get(spec.name, "uniform")
            if placement == "quantile":
                basis = BSplineBasis1D.from_quantiles(inputs[:, input_index], n_intervals, term_spec.degree,
                                                      lower=spec.lower, upper=spec.upper)
            else:
                basis = BSplineBasis1D.uniform(spec.lower, spec.upper, n_intervals, term_spec.degree)
            bases.append(basis)
        terms.append(TensorTerm(term_spec.name, tuple(term_spec.input_indices), bases, term_spec.penalty_order,
                                [term_spec.initial_smoothing] * len(bases)))
    total = sum(t.n_coefficients for t in terms)
    return SumOfTermsSpline(specs, terms, np.zeros(total), dict(metadata or {}))
