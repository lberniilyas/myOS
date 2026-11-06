"""Field types shared by request schemas."""

from typing import Annotated

from pydantic import StringConstraints

# A name or title: surrounding spaces are dropped and something has to remain.
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
