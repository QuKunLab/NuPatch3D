# npe2 模式下，__init__.py 可以为空，
# 或者只用来暴露你希望用户在脚本中 import 的类。

try:
    from ._widget import NuPatch3DWidget
except ImportError:
    pass

# 不需要 napari_hook_implementation 了