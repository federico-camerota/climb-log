# SPDX-License-Identifier: GPL-3.0-or-later
"""Print the backend's OpenAPI schema as JSON (D-073).

`make api-types` turns it into `frontend/src/api/schema.ts` with openapi-typescript, and
`make lint` checks that the committed file is up to date. The app is built, not served: no
config, network or server is needed.
"""

import json
import sys

from climblog.main import create_app


def main() -> None:
    json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
