import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dboptima.data_generator import generate  # noqa: E402
from dboptima.pipeline import Scenario, run  # noqa: E402


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("synthetic")
    generate(d)
    return d


@pytest.fixture(scope="session")
def analysis(data_dir):
    return run(Scenario(), data_dir=data_dir, persist=False)


@pytest.fixture(scope="session")
def analysis_oracle_down(data_dir):
    return run(Scenario(oracle_discovery_unavailable=True), data_dir=data_dir, persist=False)
