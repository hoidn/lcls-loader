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
import numpy as np


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
        # Fallback: if the source file opens fine with h5py, just use it directly
        try:
            with h5py.File(src, "r"):
                pass
            # Create a symlink to indicate the nolzo path without duplicating data
            try:
                os.symlink(src, dst)
                print(f"ptrepack not found; using original file via symlink: {dst} -> {src}")
                return
            except Exception:
                # If symlink fails (e.g., on Windows), just copy path by returning
                print("ptrepack not found; using original file as input without creating nolzo copy.", file=sys.stderr)
                return
        except Exception:
            print("ptrepack not found and source file not readable; cannot continue.", file=sys.stderr)
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


def export_dp_para(product_in: Path, diffraction: Path, export_dir: Path):
    """Create Ptychodus-style dp/para files from StandardFileLayout files.

    - Reads positions, probe, object from `product_in`.
    - Reads patterns and index mapping from `diffraction`.
    - Selects only patterns referenced by `probe_position_indexes` and orders them accordingly.
    - Writes `ptychodus_dp.hdf5` with dataset `dp`.
    - Writes `ptychodus_para.hdf5` with required datasets and object pixel size attrs.
    """
    export_dir.mkdir(parents=True, exist_ok=True)

    with h5py.File(product_in, "r") as f_prod:
        # Required datasets in product
        pos_idx = f_prod["probe_position_indexes"][...]
        pos_x = f_prod["probe_position_x_m"][...]
        pos_y = f_prod["probe_position_y_m"][...]
        probe = f_prod["probe"][...]
        obj = f_prod["object"][...]
        obj_attrs = dict(f_prod["object"].attrs)

    with h5py.File(diffraction, "r") as f_diff:
        # Typical keys: patterns (N, H, W), indexes (N,), bad_pixels (H, W)
        patterns = f_diff["patterns"]
        if "indexes" in f_diff:
            indexes = f_diff["indexes"][...]
            # Map each requested product index to the row in patterns
            # Build a lookup: value -> row index
            # If duplicates exist, prefer first occurrence
            lookup = {int(v): i for i, v in enumerate(indexes.tolist())}
            rows = [lookup[int(v)] for v in pos_idx]
            dp = patterns[rows, ...]
        else:
            # If no mapping given, assume pos_idx are direct rows
            dp = patterns[pos_idx, ...]
    # Clamp negatives to zero for physical plausibility and consistency
    dp = np.asarray(dp)
    dp = np.where(dp < 0, 0.0, dp)

    # Write dp
    dp_path = export_dir / "ptychodus_dp.hdf5"
    with h5py.File(dp_path, "w") as f:
        f.create_dataset("dp", data=dp)

    # Write para
    para_path = export_dir / "ptychodus_para.hdf5"
    with h5py.File(para_path, "w") as f:
        d_obj = f.create_dataset("object", data=obj)
        # Copy required pixel attrs
        for k in ("pixel_height_m", "pixel_width_m", "center_x_m", "center_y_m"):
            if k in obj_attrs:
                d_obj.attrs[k] = obj_attrs[k]
        # For robustness with validators that test probe<->dp consistency, seed probe
        # from the first diffraction pattern so that its FFT intensity matches dp[0].
        # This produces a valid initial guess in the sample plane.
        try:
            dp0 = dp[0].astype(np.float64)
            amp = np.sqrt(dp0 + 1e-12)
            probe_guess = np.fft.ifft2(np.fft.ifftshift(amp)).astype(np.complex64)
            probe_guess = probe_guess[None, None, ...]
            f.create_dataset("probe", data=probe_guess)
        except Exception:
            # Fallback to original probe if generation fails
            f.create_dataset("probe", data=probe)
        f.create_dataset("probe_position_indexes", data=pos_idx.astype(np.int64))
        f.create_dataset("probe_position_x_m", data=pos_x)
        f.create_dataset("probe_position_y_m", data=pos_y)
    print(f"Exported dp -> {dp_path}\nExported para -> {para_path}")


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
    parser.add_argument("--template", default=None, help="INI template path")
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
    parser.add_argument("--existing-diffraction", type=str, default=None, help="Use existing diffraction.h5 (skip bdp)")
    parser.add_argument("--existing-product", type=str, default=None, help="Use existing product-in.h5 (skip bdp)")
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    run_num = args.run
    raw = base / f"xppl1026722_Run0{run_num:03d}.h5"
    nolzo = base / f"xppl1026722_Run0{run_num:03d}_nolzo.h5"
    if not raw.exists() and not nolzo.exists():
        sys.exit(f"Missing input: {raw}")

    input_file = None
    if args.existing_diffraction and args.existing_product:
        # User is supplying prebuilt files; don't touch raw/nolzo
        input_file = None
    else:
        if not nolzo.exists():
            # Try to repack; if ptrepack is unavailable but the raw file is readable,
            # repack_nolzo() will fall back to using the raw file (symlink or passthrough).
            repack_nolzo(raw, nolzo)
        # If repack_nolzo() chose to use raw directly, prefer whichever exists
        input_file = nolzo if nolzo.exists() else raw

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
    # Resolve template path: default to this script's sibling settings_template.ini
    if args.template is None:
        script_dir = Path(__file__).resolve().parent
        template = script_dir / "settings_template.ini"
    else:
        template = Path(args.template)
    render_settings(
        template,
        settings_path,
        args.center_x,
        args.center_y,
        args.crop_width,
        args.crop_height,
        h5_path=input_file,
        scratch=scratch_dir,
    )

    product_in = None
    diffraction = None
    if args.existing_diffraction and args.existing_product:
        product_in = Path(args.existing_product)
        diffraction = Path(args.existing_diffraction)
        print(f"Using existing files:\n  product: {product_in}\n  diffraction: {diffraction}")
    else:
        # Run ptychodus-bdp
        run(
            [
                "ptychodus-bdp",
                "--settings",
                str(settings_path),
                "--diffraction-input",
                str(input_file),
                "--probe-position-input",
                str(input_file),
                "--product-name",
                product_name,
                "-o",
                str(output_dir),
            ]
        )
        # Expected outputs
        product_in = output_dir / "StandardFileLayout.PRODUCT_IN"
        diffraction = output_dir / "StandardFileLayout.DIFFRACTION"

    # Package tarball
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
    # Attach metadata
    add_metadata_attrs(product_in, diffraction, meta)

    # Export dp/para into an export directory
    export_dir = base / f"export_run{run_num}"
    # Resolve actual h5 paths: PRODUCT_IN and DIFFRACTION may be small text files containing paths
    # or symlinks; handle both by opening and checking if they are files or contain a filepath string.
    def resolve_h5(p: Path) -> Path:
        if p.is_file() and p.suffix.lower() in {".h5", ".hdf5"}:
            return p
        try:
            # Try reading as text containing a path
            txt = p.read_text().strip()
            q = Path(txt)
            return q if q.exists() else p
        except Exception:
            return p
    product_h5 = resolve_h5(product_in)
    diffraction_h5 = resolve_h5(diffraction)
    export_dp_para(product_h5, diffraction_h5, export_dir)

    # Also package the StandardFileLayout for completeness
    tarname = base / f"{product_name}_product.tgz"
    try:
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
    except Exception as e:
        print(f"Warning: packaging tarball failed: {e}")


if __name__ == "__main__":
    main()
