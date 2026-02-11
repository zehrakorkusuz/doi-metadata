"""Allow ``python -m benchmark`` as a shorthand for ``python -m benchmark.pipeline``."""

from benchmark.pipeline import main

if __name__ == "__main__":
    main()
