"""
Command line: fit the correction map and the no-read map from a manifest or
from a directory of captures with header poses, write the map files and a
validation report.

    python3 -m sphcal.cli.fit --manifest data/manifest.json --out results/
    python3 -m sphcal.cli.fit --directory data/ --target sphere --radius-mm 50 --out results/
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sphcal.calibration.correction import CorrectionFitParameters, fit_correction
from sphcal.calibration.noread import NoReadFitParameters, fit_noread
from sphcal.io.capture_set import CaptureSet
from sphcal.io.poses import load_manifest, records_from_headers
from sphcal.validation.report import ReportParameters, binned_residuals, board_normal_bias, plot_residuals_by_incidence, \
    sphere_center_errors, write_report


def build_capture_set(args: argparse.Namespace) -> CaptureSet:
    if args.manifest:
        return CaptureSet(load_manifest(Path(args.manifest)))
    paths = sorted(Path(args.directory).glob("*.mc"))
    if args.target == "sphere":
        records = records_from_headers(paths, "sphere", sphere_radius_mm=args.radius_mm)
    else:
        records = records_from_headers(paths, "board", board_half_size_mm=(args.half_width_mm, args.half_height_mm))
    return CaptureSet(records)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", help="manifest JSON or CSV")
    source.add_argument("--directory", help="directory of .mc files whose headers carry the pose")
    parser.add_argument("--target", choices=("sphere", "board"), default="sphere")
    parser.add_argument("--radius-mm", type=float)
    parser.add_argument("--half-width-mm", type=float)
    parser.add_argument("--half-height-mm", type=float)
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--no-gcv", action="store_true", help="skip the GCV search over smoothing parameters")
    parser.add_argument("--skip-noread", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    capture_set = build_capture_set(args)
    params = CorrectionFitParameters()
    if args.no_gcv:
        params = CorrectionFitParameters(smoothing_grid=None)
    result = fit_correction(capture_set, params)
    result.model.metadata.update({"sensor_to_positioner": result.sensor_to_positioner.as_matrix().tolist(),
                                  "training_poses": result.training_poses, "holdout_poses": result.holdout_poses})
    result.model.to_json(out / "correction_map.json")
    report_params = ReportParameters()
    report = {"rounds": [{"round": r.round_index, "translation_change_mm": r.translation_change_mm,
                          "rotation_change_deg": r.rotation_change_deg, "training_rms_mm": r.training_residual_rms_mm,
                          "rigid_translation_mm": r.rigid_translation_mm.tolist(),
                          "rigid_rotation_deg": r.rigid_rotation_deg.tolist()} for r in result.rounds],
              "sensor_to_positioner": result.sensor_to_positioner.as_matrix().tolist(),
              "training": binned_residuals(result.training_samples, result.model, report_params)}
    if result.holdout_samples is not None:
        report["holdout"] = binned_residuals(result.holdout_samples, result.model, report_params)
        plot_residuals_by_incidence(report["holdout"], out / "holdout_residual_by_incidence.png")
        report["holdout_sphere_centers"] = sphere_center_errors(capture_set, result.holdout_poses, result.model,
                                                                result.sensor_to_positioner, params.samples, report_params)
        report["holdout_board_normals"] = board_normal_bias(capture_set, result.holdout_poses, result.model,
                                                            result.sensor_to_positioner, params.samples, report_params)
    if not args.skip_noread:
        noread = fit_noread(capture_set, result.sensor_to_positioner, NoReadFitParameters(samples=params.samples))
        noread.model.to_json(out / "noread_map.json")
        report["noread_onset_deg"] = noread.onset_by_azimuth_deg
        report["noread_reference_range_mm"] = noread.reference_range_mm
    write_report(out / "report.json", report)
    print(json.dumps({k: report[k] for k in ("sensor_to_positioner",) if k in report}, indent=1))
    if "holdout" in report:
        print(f"held-out RMS before {report['holdout']['overall_rms_before_mm']:.4f} mm, "
              f"after {report['holdout']['overall_rms_after_mm']:.4f} mm")


if __name__ == "__main__":
    main()
