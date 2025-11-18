
## Guide: Converting LCLS HDF5 Data to Ptychodus Product Format

This guide will walk you through the process of converting raw LCLS ptychography data (typically in a single `.h5` file) into a set of files that Ptychodus can use for reconstruction. We will use the `ptychodus-bdp` (Beamline Data Pipeline) command-line tool, which is designed for this purpose.

### Prerequisites

1.  **Ptychodus Installed:** You must have a working installation of Ptychodus in a Python environment (like conda or a virtualenv). Ensure you can run `ptychodus --version` from your terminal.
2.  **LCLS Data File:** You need the path to your LCLS `.h5` data file. For this guide, we'll assume the file is named `my_lcls_data.h5`.

### Overview of the Process

The conversion involves three main steps:
1.  **Create and Configure a Settings File:** We'll generate a settings file (`.ini`) to tell Ptychodus which specific file readers (plugins) to use for your LCLS data.
2.  **Run the `ptychodus-bdp` Command:** We'll execute the script with the correct arguments to process your data.
3.  **Verify the Output:** We'll confirm that the output files were created correctly.

### Step 1: Create and Configure the Settings File

The `ptychodus-bdp` tool needs to know which plugins to use to read your diffraction patterns and scan positions. We'll specify this in a settings file.

1.  **Generate a Default Settings File:**
    The easiest way to get a valid settings file is to generate it from the Ptychodus GUI.
    -   Open your terminal and activate your Ptychodus environment.
    -   Run the graphical interface:
        ```shell
        ptychodus
        ```
    -   Once the application opens, go to the **Settings** tab.
    -   Click the **Save** button.
    -   Save the file as `lcls_settings.ini` in a location you can easily find. You can now close the Ptychodus application.

2.  **Modify the Settings File for LCLS Data:**
    Open the `lcls_settings.ini` file you just saved in a text editor. You need to tell it to use the `LCLS_XPP` reader for both diffraction and positions.

    -   Find the `[Diffraction]` section and change the `FileType` to `LCLS_XPP`.
    -   Find the `[ProbePositions]` section and change the `FileType` to `LCLS_XPP`.

    Your modified sections should look like this:

    ```ini
    [Diffraction]
    FileType = LCLS_XPP
    # ... other settings may be here ...

    [ProbePositions]
    FileType = LCLS_XPP
    # ... other settings may be here ...
    ```
    Save the changes to the file. This is the most critical step, as it tells the program how to interpret your HDF5 file.

### Step 2: Run the Conversion Command

Now we'll use the `ptychodus-bdp` script to perform the conversion.

1.  **Open your terminal** and navigate to a convenient working directory.

2.  **Execute the command** below, replacing the placeholder paths with the actual paths on your system. This command reads your LCLS file, creates a Ptychodus data product, and saves all necessary files into an output directory.

    ```shell
    ptychodus-bdp \
        --settings /path/to/your/lcls_settings.ini \
        --diffraction-input /path/to/your/my_lcls_data.h5 \
        --probe-position-input /path/to/your/my_lcls_data.h5 \
        --product-name "MyFirstLCLSProduct" \
        -o ./lcls_product_output \
        --probe-energy-eV 8000 \
        --detector-distance-m 2.5
    ```

    **Argument breakdown:**
    *   `--settings`: The full path to the `lcls_settings.ini` file you just modified.
    *   `--diffraction-input`: The path to your LCLS `.h5` file. The `LCLS_XPP` plugin knows to look for diffraction data at the `/jungfrau1M/image_img` path inside this file.
    *   `--probe-position-input`: The path to the *same* `.h5` file. The `LCLS_XPP` plugin will extract the scan positions from this file.
    *   `--product-name`: A unique name for your experiment. This will be the default name inside Ptychodus.
    *   `-o`: The output directory where Ptychodus will save the converted files. The directory will be created if it doesn't exist.
    *   `--probe-energy-eV` & `--detector-distance-m`: **(Optional but Recommended)** Use these to provide metadata that might not be in the HDF5 file. This ensures your product is correctly configured from the start.

### Step 3: Understand and Verify the Output

After the command finishes, your output directory (`./lcls_product_output` in the example) will contain the following key files:

-   **`diffraction.h5`**: An HDF5 file containing the diffraction patterns, cropped and processed according to your settings.
-   **`product-in.h5`**: The main Ptychodus product file. This contains the scan positions, an initial guess for the probe and object, and all the metadata. **This is the file you will load into Ptychodus.**
-   **`settings.ini`**: A copy of the settings used for this conversion, for reproducibility.

**To verify the conversion:**

1.  Launch the Ptychodus GUI again: `ptychodus`
2.  Go to the **Products** tab (list icon).
3.  Click **Load** > **Open File...**.
4.  Navigate to your output directory and select `product-in.h5`.

You should see a new entry in the Products table with the name you provided. You can now select it and proceed with reconstruction.

### Example Settings Included in This Directory

Two ready-to-edit settings files live alongside this guide:

- `single_recon/input.ini`: full reconstruction config pointing at `xppl1026722_Run0396.h5` with `FileType = LCLSv2` for both diffraction and scan inputs. Key values: detector distance 2 m; Jungfrau pixels 1030x1064 with 75 µm pitch; crop at (642, 331) to a 128x128 window; lower-bound threshold 20; memmap enabled with scratch dir `/sdf/home/a/avong/.ptychodus`; probe initialized as a 2 µm disk, 10 keV energy, 3 modes. Reconstruction uses Tike `lstsq_grad` with 2 GPUs, 10-batch `wobbly_center` sampling, 200 iterations, and adaptive probe/object updates.
- `single_recon/LCLS_demo/input.ini`: identical template to the above, provided as a demo copy.
- `august_demo_test/lcls_settings.ini`: minimal BDP settings pointing at the decompressed `xppl1026722_Run0171_nolzo.h5` with `FileType = LCLS_XPP` for both diffraction and scan inputs. It enables memmap to `august_demo_test/.ptychodus_scratch` and crops around the bright spot to a 256x256 window centered at (x=635, y=312). Use it directly with `ptychodus-bdp --settings august_demo_test/lcls_settings.ini --diffraction-input ... --probe-position-input ... -o ./august_demo_test/output`.

How to use them:
1. Copy one of these files to a new name (e.g., `my_run.ini`).
2. Update the HDF5 paths under `[Diffraction Dataset]` and `[Scan]` to the run you want (they currently reference run 396).
3. Adjust crop centers/extents if your diffraction peak is elsewhere, and tweak `CropExtent*` to match the area you want ptychography to use.
4. If you choose a different energy or detector distance than in your data, align `ProbeEnergyInElectronVolts` and `DetectorDistanceInMeters` accordingly.

These templates pair with the `ptychodus-bdp` workflow above: use them as your starting point for reconstruction settings once you have produced `product-in.h5`.

### Troubleshooting

*   **"Command not found: ptychodus-bdp"**: Make sure you have activated the correct conda or virtual environment where Ptychodus is installed.
*   **"[Errno 21] Is a directory"** (or similar): Ensure the path you provide to `--diffraction-input` or `--probe-position-input` is a file, not a directory.
*   If you need more detail, increase verbosity with `--log-level 10` (DEBUG) or `--log-level 20` (INFO).
*   **HDF5 filter errors (e.g., unknown compression/filter):** For common filters (LZ4/Zstd/Blosc/Bitshuffle/LZF/BZip2), installing `hdf5plugin` in the same environment usually resolves it. Example: `pip install hdf5plugin` or `conda install -c conda-forge hdf5plugin`.
*   **LZO-compressed datasets:** `hdf5plugin` and common plugin bundles (`hdf5_plugins`, `HDF5-External-Filter-Plugins`) do **not** ship LZO because of GPL licensing. If a dataset was written with LZO (seen in some LANL workflows), use one of these workarounds:
    - Verify first: `h5dump -pH my.h5 | grep -i filter` to see if `lzo` appears.
    - Preferred: use an environment that can read LZO (e.g., an older or custom PyTables build linked against `liblzo2`) and repack to gzip or uncompressed, e.g. `ptrepack --complib=zlib --complevel=4 in.h5 out.h5` or `--complevel=0` to drop compression.
    - `h5repack` can rewrite filters but still needs the LZO plugin to read the input.
    - Only if you must keep LZO: build an HDF5 LZO filter, install the shared library, and set `HDF5_PLUGIN_PATH` to point to it.
  Note: LZO use at LCLS is uncommon; for LCLS2, LZO is not under consideration. Ensure licensing compliance if you build or distribute LZO.
  *Tip from this run:* if both LZO and decompressed copies exist (e.g., `_nolzo` files), point BDP at the decompressed file to avoid plugin issues. To create a `_nolzo` copy yourself:
    1) Activate an env that can read LZO (PyTables <3.10.1 or with `liblzo2` available).
    2) Repack to a non-LZO filter, e.g. `ptrepack --complib=zlib --complevel=4 xppl1026722_Run0171.h5 xppl1026722_Run0171_nolzo.h5` (or `--complevel=0` to drop compression).
    3) Verify the new file: `h5dump -pH xppl1026722_Run0171_nolzo.h5 | grep -i filter` should no longer show `lzo`.
*   **List available plugins:** Run `convert-to-ptychodus --list-plugins` to see registered reader names. Confirm `LCLS_XPP` appears under `diffraction_readers` and `probe_position_readers` if you’re setting it in `settings.ini`.
*   **"KeyError: 'Unable to open object ...'"**: This often means the HDF5 file does not contain the expected data at the default paths. Double-check that your LCLS file contains data at `/jungfrau1M/image_img` (for diffraction) and `/lmc/ch*` (for positions). If not, the reader plugin may need to be adjusted.
*   **Working S3DF environment:** The default psana environment (`ps_20241122` on S3DF) includes PyTables 3.9.x, which can open `xppl1026722_Run0396.h5` directly (`python - <<'PY'\nimport tables; tables.open_file('...')\nPY`). You only need a special LZO plugin if your file actually used that compression.
*   **Runtime/memory pressure:** For large runs, enable `MemmapEnabled = True` and set `ScratchDirectory` to an existing writable path. Cropping to a smaller window around the bright spot (as in `august_demo_test/lcls_settings.ini`) reduces memory and runtime and avoids kill/timeout signals.
