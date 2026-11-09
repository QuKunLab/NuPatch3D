# NuPatch3D Dataset

[← Repository overview](../README.md)

**NuPatch3D Dataset** is a resource for 3D nuclear segmentation, containing approximately **1.01 million annotated nuclei** across **2,672 z-stacks**, **16 samples**, and **5 species**. It includes two microscopy modalities—**confocal** and **wide-field**—as well as simulated data. The newly acquired human, mouse, and label collections are hosted on OMIX, with public access to the human and mouse parts and access to labels upon request through the OMIX website. An additional public collection is available through USTC Cloud.

## Availability

The human, mouse, and label collections are deposited in **OMIX**. And the public collection is available through a USTC Cloud sharing link:

| Data collection | Access | Accession | Download link |
| --- | --- | --- | --- |
| **NuPatch3D dataset human** | Publicly accessible |OMIX023136 |[Download here](https://ngdc.cncb.ac.cn/omix/release/OMIX023136) |
| **NuPatch3D dataset mouse** | Publicly accessible |OMIX023144 |[Download here](https://ngdc.cncb.ac.cn/omix/release/OMIX023144) |
| **NuPatch3D dataset label** | Request access through the OMIX website, subject to applicable policies |OMIX023146 | [Download here](https://ngdc.cncb.ac.cn/omix/release/OMIX023146)|
| **NuPatch3D dataset public** | Publicly accessible |- |[Download here]() |

To access the **NuPatch3D dataset label** collection, submit a data access request through the OMIX website for the corresponding collection. We welcome requests and will approve them whenever permitted by applicable policies.

## Dataset construction

![NuPatch3D dataset construction workflow](../assets/figures/NuPatch3D_dataset_generation_pipeline.png)

**Figure 1.** Construction of the NuPatch3D dataset through biological sample collection, imaging and alignment, and refinement of initial Cellpose segmentations using NuPatch3D.

## Dataset characteristics

![NuPatch3D dataset composition and distributions of image and nuclear attributes](../assets/figures/Data_attribute.png)

**Figure 2.** Composition of the NuPatch3D dataset by sample type, data source, and acquisition method, with distributions of nuclear density, image quality and nuclear morphology.

## Related modules

[NuPatch3D Tool](../NuPatch3D-tool/README.md) · [Benchmark](../Benchmark/README.md)
