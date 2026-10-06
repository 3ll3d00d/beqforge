"""Device-specific coefficient optimisation, independent of the other workflows."""

from beq_common import __version__ as __version__

from .cache import (
    ResultCache as ResultCache,
)
from .cache import (
    optimise as optimise,
)
from .core import (
    FixedPoint as FixedPoint,
)
from .core import (
    Float32 as Float32,
)
from .core import (
    Precision as Precision,
)
from .core import (
    Result as Result,
)
from .core import (
    Section as Section,
)
from .core import (
    Settings as Settings,
)
from .core import (
    magnitude as magnitude,
)
from .core import (
    stable as stable,
)
