# NuPatch3D

**NuPatch3D** is a [napari](https://napari.org/) plugin for post-processing 3D cell nucleus segmentation results. It provides interactive tools to correct common segmentation errors, including under-segmentation, over-segmentation, missing cells, and boundary inaccuracies.

---

## Features

- **Local editing** — Extract and refine individual cells or neighborhoods in an isolated bounding box; changes are written back to the global segmentation only after you Commit
- **Under-segmentation split** — Separate merged cells using plane-based, GMM auto, manual center modes
- **Over-segmentation merge** — Merge fragmented labels or delete spurious ones
- **Boundary refinement** — Adjust cell boundaries based on local image intensity
- **Missing cell detection** — Add omitted cells via interactive seed points and watershed
- **Full undo/redo & JSON logging** — Up to 10-step undo/redo with traceable, reproducible editing workflow; supports recovery from JSON logs
- **Seamless napari integration** — Works with native napari brush, eraser, and fill tools; all operations are recorded in the unified edit history

---

## Requirements

- **OS**: Windows 10 or macOS 26 (Tahoe) and above
- **RAM**: 16 GB or more
- **napari**: 0.6.x (other versions may have compatibility issues)

## Installation

### Quick install (recommended)

```bash
pip install "git+https://github.com/QuKunLab/NuPatch3D.git#subdirectory=NuPatch3D"
```

### Local clone (for development)

```bash
git clone https://github.com/QuKunLab/NuPatch3D.git
cd NuPatch3D/NuPatch3D
pip install .
```

> **Note:** This plugin is tested on napari 0.6. Other versions may have compatibility issues.

---

## Documentation

- **User Manual:** https://qukunlab.github.io/NuPatch3D/
- **English:** https://qukunlab.github.io/NuPatch3D/en/
- **中文:** https://qukunlab.github.io/NuPatch3D/

The full user manual, video tutorials, and usage instructions are available at the links above.

---

## Repository Structure

```
NuPatch3D/
├── docs/              # MkDocs documentation source (website)
│   ├── index.md
│   ├── en/
│   └── images/
├── NuPatch3D/         # Plugin source code
│   ├── src/
│   └── pyproject.toml
├── mkdocs.yml
└── .github/workflows/ci.yml
```

- `docs/` — Documentation and website source files (built to `gh-pages` branch via GitHub Actions)
- `NuPatch3D/` — Python plugin source and `pyproject.toml` for `pip install`

---

## Citation

If you use NuPatch3D in your research, please cite this repository:

> Y. Hu, *et al.*, Benchmarking 3D nuclear segmentation with the atlas-scale NuPatch3D dataset

---

## License

This project is licensed under the MIT License.
