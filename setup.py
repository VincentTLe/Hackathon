"""
Build the C++ Bron-Kerbosch clique engine as a pybind11 extension.

Usage:
    python setup.py build_ext --inplace
"""
from setuptools import setup, Extension
import pybind11

ext = Extension(
    "clique_engine",
    sources=["core/clique_engine.cpp"],
    include_dirs=[pybind11.get_include()],
    language="c++",
    extra_compile_args=["-O3", "-std=c++17"],
)

setup(
    name="guardian_sleuth",
    version="0.1.0",
    ext_modules=[ext],
)
