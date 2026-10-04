"""
CaptureSet: capture records grouped by commanded pose, with lazy loading.

Frames of one commanded pose are loaded together as a PoseStack: the camera
frame XYZ images of all frames, a validity mask (z > 0; the sentinel for an
unread pixel is the whole point being zero), the first frame's header and the
pinhole camera built from that header and the array shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sphcal.geometry.camera import PinholeCamera
from sphcal.io.matcloud import read_matcloud
from sphcal.io.poses import CaptureRecord

XYZ_CHANNEL_NAME = "XYZ"
"""Name of the matrix holding the (H, W, 3) camera-frame points in a ``.mc`` file."""


@dataclass
class PoseStack:
    """All frames of one pose.

    xyz:    (F, H, W, 3) float32 camera-frame points in mm, frames ordered by frame_index
    valid:  (F, H, W) bool, True where z > 0
    header: header dict of the first frame
    camera: PinholeCamera from that header and the array shape
    records: the F records, in the same order as the frames
    """

    xyz: np.ndarray
    valid: np.ndarray
    header: dict
    camera: PinholeCamera
    records: list[CaptureRecord] = field(default_factory=list)


@dataclass
class CaptureSet:
    """Records of a capture session, grouped by pose id on demand."""

    records: list[CaptureRecord]

    def pose_ids(self) -> list[str]:
        """Distinct pose ids in order of first appearance."""
        return list(dict.fromkeys(record.pose_id for record in self.records))

    def records_for(self, pose_id: str) -> list[CaptureRecord]:
        """Records of one pose, ordered by frame_index (stable for ties)."""
        selected = [record for record in self.records if record.pose_id == pose_id]
        return sorted(selected, key=lambda record: record.frame_index)

    def load_stack(self, pose_id: str) -> PoseStack:
        """Read all frames of a pose. Raises KeyError for an unknown pose id and
        ValueError if the frames do not all have the same image size."""
        records = self.records_for(pose_id)
        if not records:
            raise KeyError(f"no records for pose id {pose_id!r}")
        frames: list[np.ndarray] = []
        first_header: dict | None = None
        for record in records:
            capture = read_matcloud(record.path)
            xyz = np.asarray(capture.matrices[XYZ_CHANNEL_NAME], dtype=np.float32)
            if frames and xyz.shape != frames[0].shape:
                raise ValueError(
                    f"pose {pose_id!r}: mixed image sizes, {frames[0].shape} vs {xyz.shape} in {record.path}")
            if first_header is None:
                first_header = capture.header
            frames.append(xyz)
        stack = np.stack(frames, axis=0)
        height, width = stack.shape[1], stack.shape[2]
        camera = PinholeCamera.from_matcloud_header(first_header, width_px=width, height_px=height)
        return PoseStack(xyz=stack, valid=stack[..., 2] > 0.0, header=first_header, camera=camera,
                         records=records)
