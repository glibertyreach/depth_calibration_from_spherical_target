"""
The no-read probability map (step S5): a penalized logistic sum-of-terms
B-spline fitted to the per-pixel read fraction over every pixel the known
targets cover, indexed by PREDICTED geometry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sphcal.calibration.model_config import ModelConfiguration, build_model, noread_configuration
from sphcal.calibration.samples import NoReadTable, SampleParameters, build_noread_samples
from sphcal.geometry.transforms import RigidTransform
from sphcal.io.capture_set import CaptureSet
from sphcal.spline.fit import LogisticParameters, fit_logistic
from sphcal.spline.model import SumOfTermsSpline


@dataclass(frozen=True)
class NoReadFitParameters:
    samples: SampleParameters = field(default_factory=SampleParameters)
    model: ModelConfiguration = field(default_factory=noread_configuration)
    logistic: LogisticParameters = field(default_factory=LogisticParameters)
    onset_probability: float = 0.5
    """The read probability whose contour is reported as the no-read onset."""
    onset_incidence_grid_deg: tuple[float, float, float] = (0.0, 85.0, 1.0)
    """(start, stop, step) of the incidence sweep used to locate the onset."""


@dataclass
class NoReadFitResult:
    model: SumOfTermsSpline
    samples: NoReadTable
    onset_by_azimuth_deg: dict      # azimuth label -> onset incidence in degrees at the reference range, or None
    reference_range_mm: float


def read_probability(model: SumOfTermsSpline, inputs: np.ndarray) -> np.ndarray:
    """Probability of a read from the logit map."""
    logit = model.evaluate(inputs)
    return 1.0 / (1.0 + np.exp(-logit))


def _onset_along_azimuth(model: SumOfTermsSpline, u: float, v: float, range_mm: float, azimuth_deg: float,
                         curvature: float, params: NoReadFitParameters) -> float | None:
    """Incidence at which the read probability crosses the onset value along one slope azimuth."""
    start, stop, step = params.onset_incidence_grid_deg
    incidence = np.arange(start, stop + step, step)
    tan_a = np.tan(np.radians(incidence))
    inputs = np.column_stack([np.full_like(tan_a, u), np.full_like(tan_a, v), np.full_like(tan_a, range_mm),
                              tan_a * np.cos(np.radians(azimuth_deg)), tan_a * np.sin(np.radians(azimuth_deg)),
                              np.full_like(tan_a, curvature)])
    inside = (np.abs(inputs[:, 3]) <= model.inputs[3].upper) & (np.abs(inputs[:, 4]) <= model.inputs[4].upper)
    p = read_probability(model, inputs[inside])
    below = np.nonzero(p < params.onset_probability)[0]
    return float(incidence[inside][below[0]]) if below.size else None


def fit_noread(capture_set: CaptureSet, sensor_to_positioner: RigidTransform, params: NoReadFitParameters) -> NoReadFitResult:
    samples = build_noread_samples(capture_set, sensor_to_positioner, params.samples)
    first = capture_set.load_stack(capture_set.pose_ids()[0])
    camera = first.camera
    model = build_model(params.model, samples.inputs, camera.width, camera.height,
                        metadata={"output": "logit of read probability", "indexed_by": "predicted geometry"})
    design = model.design(samples.inputs)
    result = fit_logistic(design, samples.read_fraction, samples.trials, model.penalty(), params.logistic)
    model.coefficients = result.coefficients
    reference_range = float(np.median(samples.inputs[:, 2]))
    center_u, center_v = (camera.width - 1) / 2.0, (camera.height - 1) / 2.0
    onsets = {}
    for label, azimuth in (("along_u", 0.0), ("along_v", 90.0), ("against_u", 180.0), ("against_v", 270.0)):
        onsets[label] = _onset_along_azimuth(model, center_u, center_v, reference_range, azimuth, 0.0, params)
    return NoReadFitResult(model, samples, onsets, reference_range)
