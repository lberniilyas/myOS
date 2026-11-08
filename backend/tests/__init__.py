import os

# The background sweep would use the real database; tests run it by hand instead.
os.environ.setdefault("CAPTURE_WORKER", "false")
