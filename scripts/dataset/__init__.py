"""SupportNova complaint-dataset generator (fictional Lumora Home Technologies).

The package turns a human-readable *scenario bank* (``scenarios/*.yaml``) into
the dev and holdout complaint datasets:

* ``common``     - paths, constants and deterministic RNG helpers
* ``textutil``   - text joining, normalisation, date/amount/duration formatting, similarity
* ``lexicon``    - lexical signal detector used for the coherence self-check
* ``catalog``    - product catalogue and natural product mentions
* ``customers``  - simulated customer base
* ``ledger``     - simulated order ledger and named order profiles
* ``scenarios``  - scenario-bank loader and structural validation
* ``render``     - slot rendering and channel adaptation
* ``builder``    - end-to-end generation (scheduling, labelling, linking, ID assignment)
* ``records``    - record assembly helpers shared by the generator and the validator
* ``summary``    - dataset summary and SRS-minimum checks

Expected labels are produced by applying the approved Rule Matrix to the
*declared* scenario facts with ``supportnova.rule_engine.reference.label_declared``.
"""

from .common import ensure_backend_path

ensure_backend_path()  # backend/src must be importable before any module imports ``supportnova``
