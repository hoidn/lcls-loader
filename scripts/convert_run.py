#!/usr/bin/env python3
"""
Batch helper to convert an LCLS XPP run into a Ptychodus product.

Steps:
1) Repack LZO-compressed smalldata file to a "_nolzo" copy (using PyTables if available).
2) Generate a settings ini from a template, applying crop center/size.
3) Run ptychodus-bdp to produce the product.
4) Package outputs into a tarball with descriptive names.

Requires: ptychodus-bdp on PATH; PyTables (for repacking) if you want auto _nolzo generation.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
import h5py
import json
try:
    import yaml
except ImportError:
    yaml = None


def run(cmd, **kwargs):
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd, **kwargs)


def repack_nolzo(src: Path, dst: Path):
    """Use ptrepack to rewrite compression (requires an env that can read LZO)."""
    if dst.exists():
        print(f"nolzo already exists: {dst}")
        return
    try:
        run(
            [
                "ptrepack",
                "--complib=zlib",
                "--complevel=4",
                str(src),
                str(dst),
            ]
        )
    except FileNotFoundError:
        print("ptrepack not found; skip repack. Create nolzo manually.", file=sys.stderr)
        sys.exit(1)


def render_settings(
    template: Path,
    out_ini: Path,
    crop_x: int,
    crop_y: int,
    width: int,
    height: int,
    h5_path: Path,
    scratch: Path,
):
    text = template.read_text()
    text = text.replace("{CROP_X}", str(crop_x))
    text = text.replace("{CROP_Y}", str(crop_y))
    text = text.replace("{CROP_W}", str(width))
    text = text.replace("{CROP_H}", str(height))
    text = text.replace("XPPL_HDF5_PATH_PLACEHOLDER", str(h5_path))
    text = text.replace("XPPL_SCRATCH_PLACEHOLDER", str(scratch))
    out_ini.write_text(text)
    print(f"Wrote settings to {out_ini}")


def add_metadata_attrs(product_in: Path, diffraction: Path, meta: dict):
    """Attach geometry metadata to product and diffraction files."""
    def _write(path: Path):
        with h5py.File(path, "r+") as f:
            for k, v in meta.items():
                f["/"].attrs[k] = v
    _write(product_in)
    if diffraction.exists():
        _write(diffraction)


def load_geometry_config(path: Path):
    if not path:
        return {}
    text = path.read_text()
    if path.suffix.lower() in {".yml", ".yaml"}:
        if yaml is None:
            raise RuntimeError("pyyaml not installed; cannot read YAML config")
        return yaml.safe_load(text)
    return json.loads(text)


def value_for_run(ranges, run, fallback):
    if not ranges:
        return fallback
    for entry in ranges:
        runs = entry.get("runs")
        if not runs or len(runs) != 2:
            continue
        start, end = runs
        if start <= run <= end:
            return entry.get("value", fallback)
    return fallback


def main():
    parser = argparse.ArgumentParser(description="Convert LCLS run to Ptychodus product.")
    parser.add_argument("--run", required=True, type=int, help="Run number, e.g. 396")
    parser.add_argument("--center-x", type=int, required=True, help="Crop center X (pixels)")
    parser.add_argument("--center-y", type=int, required=True, help="Crop center Y (pixels)")
    parser.add_argument("--crop-width", type=int, default=512, help="Crop width (pixels)")
    parser.add_argument("--crop-height", type=int, default=512, help="Crop height (pixels)")
    parser.add_argument("--base-dir", default=".", help="Base directory containing smalldata HDF5 files")
    parser.add_argument("--template", default="scripts/settings_template.ini", help="INI template path")
    parser.add_argument("--product-name", help="Override product name")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    parser.add_argument("--scratch", default=None, help="Scratch directory for memmap")
    parser.add_argument("--detector-distance-m", type=float, default=4.05, help="Detector distance metadata")
    parser.add_argument("--photon-energy-ev", type=float, default=8800.0, help="Photon energy metadata")
    parser.add_argument("--osa_sample_distance_m", type=float, default=7.0e-3, help="OSA-to-sample distance metadata")
    parser.add_argument("--osa_upstream_distance_m", type=float, default=4.7e-2, help="OSA upstream distance metadata")
    parser.add_argument("--zone_plate_outer_radius_m", type=float, default=75e-6, help="Zone plate outer radius metadata")
    parser.add_argument("--zone_plate_focal_length_m", type=float, default=5.32e-2, help="Zone plate focal length metadata")
    parser.add_argument("--sample_probe_distance_m", type=float, default=None, help="Sample-probe distance metadata (override)")
    parser.add_argument("--geometry-config", type=str, default=None, help="YAML/JSON with run-range geometry overrides")
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    run_num = args.run
    raw = base / f"xppl1026722_Run0{run_num:03d}.h5"
    nolzo = base / f"xppl1026722_Run0{run_num:03d}_nolzo.h5"
    if not raw.exists() and not nolzo.exists():
        sys.exit(f"Missing input: {raw}")

    if not nolzo.exists():
        repack_nolzo(raw, nolzo)

    product_name = args.product_name or f"run{run_num}_center{args.center_x}_{args.center_y}"
    output_dir = Path(args.output_dir) if args.output_dir else base / f"output_run{run_num}_center"
    output_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir = Path(args.scratch) if args.scratch else base / ".ptychodus_scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    geom_cfg = load_geometry_config(Path(args.geometry_config)) if args.geometry_config else {}
    detector_distance = args.detector_distance_m if args.detector_distance_m is not None else value_for_run(geom_cfg.get("detector_distance_m"), run_num, 4.05)
    sample_probe_distance = args.sample_probe_distance_m if args.sample_probe_distance_m is not None else value_for_run(geom_cfg.get("sample_probe_distance_m"), run_num, 1.45e-3)

    # Prepare settings ini
    settings_path = output_dir / f"lcls_settings_run{run_num}.ini"
    template = Path(args.template)
    render_settings(
        template,
        settings_path,
        args.center_x,
        args.center_y,
        args.crop_width,
        args.crop_height,
        h5_path=nolzo,
        scratch=scratch_dir,
    )

    # Run ptychodus-bdp
    run(
        [
            "ptychodus-bdp",
            "--settings",
            str(settings_path),
            "--diffraction-input",
            str(nolzo),
            "--probe-position-input",
            str(nolzo),
            "--product-name",
            product_name,
            "-o",
            str(output_dir),
        ]
    )

    # Package tarball
    product_in = output_dir / "StandardFileLayout.PRODUCT_IN"
    diffraction = output_dir / "StandardFileLayout.DIFFRACTION"
    settings_copy = output_dir / "StandardFileLayout.SETTINGS"

    # Attach geometry metadata
    meta = {
        "detector_distance_m": detector_distance,
        "photon_energy_eV": args.photon_energy_ev,
        "osa_sample_distance_m": args.osa_sample_distance_m,
        "osa_upstream_distance_m": args.osa_upstream_distance_m,
        "zone_plate_outer_radius_m": args.zone_plate_outer_radius_m,
        "zone_plate_focal_length_m": args.zone_plate_focal_length_m,
        "sample_probe_distance_m": sample_probe_distance,
    }
    add_metadata_attrs(product_in, diffraction, meta)
    tarname = base / f"{product_name}_product.tgz"
    cmd = [
        "tar",
        "czf",
        str(tarname),
        "-C",
        str(output_dir),
        "StandardFileLayout.PRODUCT_IN",
        "StandardFileLayout.DIFFRACTION",
        "StandardFileLayout.SETTINGS",
    ]
    run(cmd)
    print(f"Tarball: {tarname}")


if __name__ == "__main__":
    main()
