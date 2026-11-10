"""Safety checks for the HEP explainer toolkit.

Run from the repository root:

    python -m checks.confidentiality scan PATH
    python -m checks.traceability check PATH --manifest sources.yaml
    python -m checks.diagrams check scene.yaml

Both tools use the Python 3.12 standard library only.
"""

__version__ = "0.1.0"
