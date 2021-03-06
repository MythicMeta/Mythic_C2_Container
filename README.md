# Mythic C2 Container

The `mythic_c2_container` package creates an easy way to get everything set up in a new C2 container for a Mythic supported C2 Profile. Mythic is a Command and Control (C2) framework for Red Teaming. The code is on GitHub (https://github.com/its-a-feature/Mythic) and the Mythic project's documentation is on GitBooks (https://docs.mythic-c2.net). This code will be included in the default Mythic C2 containers, but is available for anybody making custom containers as well.

## Installation

You can install the mythic scripting interface from PyPI:

```
pip install mythic-c2-container
```

## How to use

Version 0.0.23 of the `mythic_c2_container` package supports version 2.2.12 of the Mythic project. This container reports to mythic as version 4 (PyPi version 0.0.23).

For the main execution of the heartbeat and service functionality, simply import and start the service:
```
from mythic_c2_container import mythic_service
mythic_service.start_service_and_heartbeat(debug=False)
```
You can also pass `debug=True` to the start_service_and_heartbeat() function to get detailed debugging information

For a C2 Profile's code to leverage the C2ProfileBase or RPC functionality:
```
from mythic_c2_container import C2ProfileBase
from mythic_c2_container.MythicRPC import MythicRPC
response = await MythicRPC().execute("function name", **kwargs)
```

You can get the Mythic version of this package with the `get_version_info` function:

```
from mythic_c2_container.mythic_service import get_version_info
get_version_info()
```

## Where is the code?

The code for this PyPi package can be found at https://github.com/MythicMeta/Mythic_C2Profile_Container 

