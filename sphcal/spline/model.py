"""
Sum-of-terms spline model and its JSON map file.

What this module computes
-------------------------
SumOfTermsSpline is the correction map: the sum over tensor-product B-spline
terms of the term value at that term's inputs. It holds the coefficients of all
terms in one vector (term order, each term row-major over its dimensions; see
term.py), builds the joint design and penalty matrices for fitting, evaluates
the map, and reads and writes the JSON file of design document section 7.

JSON evaluation rule (what evaluate() does and what a separate evaluator must
mirror)
-----------------------------------------------------------------------------
For each term, for each of its dimensions d, with input value x taken from
X[input_indices[d]]:
  1. Clamp x to [knots_d[0], knots_d[-1]].
  2. Find the span i = the largest index with knots_d[i] <= x, limited to
     degree <= i <= n_d - 1 (n_d = len(knots_d) - degree - 1). x at the upper
     bound uses i = n_d - 1.
  3. Compute the degree + 1 nonzero basis values N_d[0..degree], belonging to
     basis functions i - degree .. i, by the Cox-de Boor recursion
     (Piegl and Tiller A2.2, as in basis.py).
The term value is the sum over all (degree + 1)^D combinations (r_0, ...,
r_{D-1}) of coefficient[flat index of (i_0 - degree + r_0, ...)] times the
product over d of N_d[r_d], where the flat index is row-major with the first
dimension slowest. The map value is the sum of the term values.

Extensions to the format of section 7 (ignored by an evaluator): each term also
stores "penalty_order" and "smoothing" so a model can be refitted after a round
trip; the top-level keys "format", "version", "inputs", "output", "terms",
"domain_note" and "metadata" are as specified.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import scipy.sparse as sp

from .basis import BSplineBasis1D
from .term import DEFAULT_PENALTY_ORDER, TensorTerm

# Identification of the map file format and its current version.
FORMAT_NAME = "sphcal-map"
FORMAT_VERSION = 1

# Default description of the model output, written to the "output" JSON key.
DEFAULT_OUTPUT = {
    "name": "delta_range",
    "unit": "mm",
    "applies_to": "range along the pixel ray, added to the measured range",
}

# Text of the "domain_note" JSON key.
DOMAIN_NOTE = "evaluate only inside the input bounds; outside, clamp inputs to the bounds"


@dataclass(frozen=True)
class InputSpec:
    """One model input: its name, nominal bounds, and unit."""

    name: str
    lower: float
    upper: float
    unit: str


def _json_default(value):
    """Convert numpy scalars and arrays inside metadata to plain JSON types."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"metadata value of type {type(value).__name__} is not JSON serializable")


@dataclass
class SumOfTermsSpline:
    """Sum of tensor-product B-spline terms.

    Attributes
    ----------
    inputs : list[InputSpec]
        The columns of the input matrix X, in order. The bounds are informational;
        evaluation clamps to each term dimension's knot range.
    terms : list[TensorTerm]
    coefficients : np.ndarray
        All term coefficients concatenated in term order; zeros if not given.
    metadata : dict
        Free-form, stored verbatim in the JSON file.
    output : dict
        Description of the output quantity (JSON "output" key).
    """

    inputs: list
    terms: list
    coefficients: np.ndarray = None
    metadata: dict = field(default_factory=dict)
    output: dict = field(default_factory=lambda: dict(DEFAULT_OUTPUT))

    def __post_init__(self) -> None:
        self.inputs = list(self.inputs)
        self.terms = list(self.terms)
        for term in self.terms:
            if max(term.input_indices) >= len(self.inputs):
                raise ValueError(f"term {term.name!r} refers to an input that does not exist")
        if self.coefficients is None:
            self.coefficients = np.zeros(self.n_coefficients)
        self.coefficients = np.asarray(self.coefficients, dtype=np.float64).reshape(-1)
        if self.coefficients.size != self.n_coefficients:
            raise ValueError(
                f"expected {self.n_coefficients} coefficients, got {self.coefficients.size}"
            )

    @property
    def n_coefficients(self) -> int:
        """Total number of coefficients over all terms."""
        return sum(term.n_coefficients for term in self.terms)

    def term_slices(self) -> list:
        """Slice of the coefficient vector belonging to each term, in term order."""
        slices = []
        start = 0
        for term in self.terms:
            slices.append(slice(start, start + term.n_coefficients))
            start += term.n_coefficients
        return slices

    def _check_inputs(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2 or X.shape[1] != len(self.inputs):
            raise ValueError(f"X must have shape (N, {len(self.inputs)})")
        return X

    def design(self, X) -> sp.csr_matrix:
        """Joint sparse design matrix, shape (N, n_coefficients): term designs side by side."""
        X = self._check_inputs(X)
        return sp.hstack([term.design(X) for term in self.terms], format="csr")

    def penalty(self) -> sp.csr_matrix:
        """Block-diagonal penalty of all terms (each with its own smoothing), sparse."""
        return sp.block_diag([term.penalty() for term in self.terms], format="csr")

    def evaluate(self, X) -> np.ndarray:
        """Map value at each row of X (N, n_inputs): the sum of the term evaluations, shape (N,)."""
        X = self._check_inputs(X)
        total = np.zeros(X.shape[0])
        for term, term_slice in zip(self.terms, self.term_slices()):
            total += term.evaluate(X, self.coefficients[term_slice])
        return total

    def copy(self) -> "SumOfTermsSpline":
        """Deep copy (terms, bases, coefficients, metadata)."""
        return copy.deepcopy(self)

    # ------------------------------------------------------------------ JSON

    def to_dict(self) -> dict:
        """The JSON document (design document section 7) as a dict."""
        terms = []
        for term, term_slice in zip(self.terms, self.term_slices()):
            degrees = {basis.degree for basis in term.bases}
            if len(degrees) != 1:
                raise ValueError(f"term {term.name!r}: the JSON format has one degree per term")
            terms.append(
                {
                    "name": term.name,
                    "input_indices": list(term.input_indices),
                    "degree": degrees.pop(),
                    "knots": [basis.knots.tolist() for basis in term.bases],
                    "coefficients": self.coefficients[term_slice].tolist(),
                    "penalty_order": term.penalty_order,
                    "smoothing": list(term.smoothing),
                }
            )
        return {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "inputs": [
                {"name": spec.name, "lower": spec.lower, "upper": spec.upper, "unit": spec.unit}
                for spec in self.inputs
            ],
            "output": dict(self.output),
            "terms": terms,
            "domain_note": DOMAIN_NOTE,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, document: dict) -> "SumOfTermsSpline":
        """Build a model from a JSON document dict, validating format and version."""
        if document.get("format") != FORMAT_NAME:
            raise ValueError(f"not a {FORMAT_NAME} document")
        if document.get("version") != FORMAT_VERSION:
            raise ValueError(f"unsupported {FORMAT_NAME} version {document.get('version')!r}")
        inputs = [
            InputSpec(spec["name"], spec["lower"], spec["upper"], spec["unit"])
            for spec in document["inputs"]
        ]
        terms = []
        coefficient_blocks = []
        for entry in document["terms"]:
            bases = [BSplineBasis1D(entry["degree"], knots) for knots in entry["knots"]]
            terms.append(
                TensorTerm(
                    name=entry["name"],
                    input_indices=tuple(entry["input_indices"]),
                    bases=bases,
                    penalty_order=entry.get("penalty_order", DEFAULT_PENALTY_ORDER),
                    smoothing=list(entry.get("smoothing", [])),
                )
            )
            coefficient_blocks.append(np.asarray(entry["coefficients"], dtype=np.float64))
        coefficients = np.concatenate(coefficient_blocks) if coefficient_blocks else np.zeros(0)
        return cls(
            inputs=inputs,
            terms=terms,
            coefficients=coefficients,
            metadata=document.get("metadata", {}),
            output=document.get("output", dict(DEFAULT_OUTPUT)),
        )

    def to_json(self, path) -> None:
        """Write the map file. Floats are written with full round-trip precision;
        NaN or infinite coefficients are refused so the file is strict JSON."""
        text = json.dumps(self.to_dict(), default=_json_default, allow_nan=False)
        Path(path).write_text(text, encoding="utf-8")

    @classmethod
    def from_json(cls, path) -> "SumOfTermsSpline":
        """Read a map file written by to_json (or by another producer of the format)."""
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
