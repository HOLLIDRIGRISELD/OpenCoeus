"""OpenCoeus — local-first hybrid AI file organisation and document retrieval.

The package is organised into the following layers:

``core``            Configuration, exceptions, logging, constants.
``domain``          Framework-independent data structures and enums.
``infrastructure``  Database, repositories and filesystem adapters.
``processing``      Scanning, metadata, hashing and document extraction.
``intelligence``    Embeddings, classification, naming and folder recommendations.
``organisation``    Rules, planning, validation, execution and recovery.
``search``          Keyword, semantic and hybrid retrieval.
``services``        Application services that coordinate the layers above.
``ui``              PySide6 desktop interface.

The dependency direction is always inward: ``ui`` -> ``services`` ->
(``processing``, ``intelligence``, ``organisation``, ``search``) ->
``infrastructure`` -> ``domain`` -> ``core``.
"""

__version__ = "0.6.0"
__product_name__ = "OpenCoeus"
__tagline__ = "Your files. Understood. Organised."
