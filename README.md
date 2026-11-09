# NuPatch3D

**NuPatch3D** brings together tools, data, and evaluation code for 3D nuclear segmentation. This repository accompanies *Benchmarking 3D nuclear segmentation with the NuPatch3D atlas*.

The repository contains three modules, each with a dedicated folder and README:

| Module | Overview | Documentation |
| --- | --- | --- |
| **[NuPatch3D Tool](./NuPatch3D-tool/README.md)** | A napari plugin for interactive correction of over-segmentation, under-segmentation, missed nuclei, and boundary errors. | [Features and installation](./NuPatch3D-tool/README.md) · [User manual](https://qukunlab.github.io/NuPatch3D/en/) |
| **[NuPatch3D Dataset](./NuPatch3D-dataset/README.md)** | A dataset with approximately 1.01 million annotated nuclei, 2,672 z-stacks, 16 samples, and 5 species | [Dataset details](./NuPatch3D-dataset/README.md) · [Data access](./NuPatch3D-dataset/README.md#availability) |
| **[Benchmark](./Benchmark/README.md)** | Evaluation and analysis code accompanying the comparison of fourteen 3D nuclear segmentation algorithms. | [Benchmark guide](./Benchmark/README.md) · [Evaluation metrics](./Benchmark/metrics/README.md) |

## NuPatch3D Tool

Interactively refine 3D nuclear segmentation results in napari, with local editing, undo/redo, JSON logging, and integration with native annotation tools.

**[Explore the tool and installation instructions →](./NuPatch3D-tool/README.md)**

## NuPatch3D Dataset

Explore annotations spanning multiple species, sample types, and imaging conditions, including representative human GBM and mouse pancreas example data. The module README provides dataset details and access instructions.

**[Explore the dataset and access information →](./NuPatch3D-dataset/README.md)**

## Benchmark

Find method-specific segmentation scripts, evaluation metrics, descriptor extraction, and analysis notebooks.

**[Explore the benchmark and evaluation instructions →](./Benchmark/README.md)**

## Repository Structure

```text
NuPatch3D/
├── README.md                    # Repository overview and module navigation
├── NuPatch3D-tool/              # NuPatch3D Tool
│   ├── README.md                # Features, installation, and user guides
│   ├── src/NuPatch3D/
│   └── pyproject.toml
├── NuPatch3D-dataset/           # NuPatch3D Dataset
│   └── README.md                # Data description, figures, and access details
├── Benchmark/                  # Benchmark
│   ├── README.md                # Benchmark overview and evaluation usage
│   ├── segmentation_scripts/
│   ├── metrics/
│   ├── descriptors/
│   └── plot/
├── assets/figures/              # Shared figures for module documentation
├── docs/                        # Tool user manual (Chinese and English)
├── mkdocs.yml
├── .github/workflows/ci.yml
└── LICENSE
```

## Citation

If you use NuPatch3D in your research, please cite:

> Y. Hu, *et al.*, Benchmarking 3D nuclear segmentation with the NuPatch3D atlas

Full publication details and a BibTeX entry will be added when available.

## Contact

For questions about NuPatch3D, contact [hyl2016@ustc.edu.cn](mailto:hyl2016@ustc.edu.cn).
