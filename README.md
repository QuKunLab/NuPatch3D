# NuPatch3D

**NuPatch3D** brings together tools, data, and evaluation code for 3D nuclear instance segmentation. This repository accompanies *Benchmarking 3D nuclear segmentation with the NuPatch3D atlas*.

The repository contains three parallel modules, each with a dedicated folder and README:

| Module | Overview | Documentation |
| --- | --- | --- |
| **[NuPatch3D Tool](./NuPatch3D%20tool/README.md)** | A napari plugin for interactive correction of over-segmentation, under-segmentation, missed nuclei, and boundary errors. | [Features and installation](./NuPatch3D%20tool/README.md) · [User manual](https://qukunlab.github.io/NuPatch3D/en/) |
| **[NuPatch3D Dataset](./NuPatch3D%20dataset/README.md)** | A dataset with approximately 1.01 million annotated nuclei, 2,672 z-stacks, 16 samples, and 5 species; human and mouse data are public, and labels are available upon request through the OMIX website. | [Dataset details](./NuPatch3D%20dataset/README.md) · [Data access](./NuPatch3D%20dataset/README.md#availability) |
| **[Benchmark](./Benchmark/README.md)** | Evaluation and analysis code accompanying the comparison of fourteen 3D nuclear segmentation algorithms. | [Benchmark guide](./benchmark/README.md) · [Evaluation metrics](./benchmark/metrics/README.md) |

## NuPatch3D Tool

Interactively refine 3D nuclear segmentation results in napari, with local editing, undo/redo, JSON logging, and integration with native annotation tools.

**[Explore the tool and installation instructions →](./NuPatch3D%20tool/README.md)**

## NuPatch3D Dataset

Explore annotations spanning multiple species, sample types, and imaging conditions, including representative human GBM and mouse pancreas data. The data are hosted on OMIX in three parts: human and mouse data are publicly accessible, while labels are available upon request through the OMIX website, subject to applicable policies. The module README provides dataset details and access instructions.

**[Explore the dataset and access information →](./NuPatch3D%20dataset/README.md)**

## Benchmark

Find method-specific segmentation scripts, instance/voxel/boundary evaluation metrics, descriptor extraction, and analysis notebooks.

**[Explore the benchmark and evaluation instructions →](./Benchmark/README.md)**

## Repository Structure

```text
NuPatch3D/
├── README.md                    # Repository overview and module navigation
├── NuPatch3D tool/              # NuPatch3D Tool
│   ├── README.md                # Features, installation, and user guides
│   ├── src/NuPatch3D/
│   └── pyproject.toml
├── NuPatch3D dataset/           # NuPatch3D Dataset
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
